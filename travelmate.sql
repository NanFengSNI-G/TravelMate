-- TravelMate MySQL 9.6 schema and demo data. Run only against an empty database.

SET NAMES utf8mb4;
SET time_zone = '+08:00';
CREATE DATABASE IF NOT EXISTS `travelmate` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE `travelmate`;




CREATE TABLE `conversations` (
	`title` VARCHAR(64) NOT NULL DEFAULT '' COMMENT '自定义会话标题；为空时从首条用户消息生成',
	`deleted` INTEGER NOT NULL DEFAULT 0 COMMENT '会话移除标记；1 表示从用户会话列表隐藏，业务记录保留',
	`created_at` INTEGER NOT NULL DEFAULT 0 COMMENT '会话创建时间，Unix 秒；旧数据为 0 时按历史消息时间排序',
	`owner` VARCHAR(64) NOT NULL COMMENT '所属用户 ID，关联 users.id；服务端用它校验会话归属',
	`history` JSON NOT NULL COMMENT '历史用户文本、结构化 Request 与 run_id 列表；助手结果关联 runs.result',
	`context_version` INTEGER NOT NULL DEFAULT 0 COMMENT '会话缓存版本；消息与运行结果变化时在同一事务递增，隔离 Redis 旧快照',
	`id` VARCHAR(64) NOT NULL COMMENT '会话唯一标识，关联 runs.conversation',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户会话表，归属校验并保存意图解析所需的历史请求';


CREATE INDEX ix_conversations_owner ON conversations (owner);


CREATE TABLE `inventory` (
	`resource` VARCHAR(64) NOT NULL COMMENT '所属资源 ID，关联 resources.id',
	`day` VARCHAR(10) NOT NULL COMMENT '库存对应日期，格式 YYYY-MM-DD；航班出发日或酒店住宿日',
	`available` INTEGER NOT NULL COMMENT '剩余可售数量；航班为座位数，酒店为该日房间数',
	`id` VARCHAR(64) NOT NULL COMMENT '库存槽位唯一标识；订单 slots 保存这些 ID',
	PRIMARY KEY (id),
	UNIQUE (resource, day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='按资源及日期记录可用库存，预订占用、取消归还';


CREATE TABLE `knowledge_nodes` (
	`revision` VARCHAR(64) NOT NULL COMMENT '所属知识版本 ID，关联 knowledge_revisions.id',
	`parent` VARCHAR(64) COMMENT '父节点 ID；顶层节点为空，完整原生关系同时保存在 Docstore',
	`section` VARCHAR(200) NOT NULL COMMENT '章节展示标签；仅供展示，不由该字段决定切分边界',
	`text` TEXT NOT NULL COMMENT '节点正文；向量由 Qdrant 保存，本字段不是向量',
	`id` VARCHAR(64) NOT NULL COMMENT 'LlamaIndex 节点 ID；检索证据通过该 ID 回查',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LlamaIndex 知识节点的 MySQL 正文镜像，用于证据核验和展示';


CREATE INDEX ix_knowledge_nodes_revision ON knowledge_nodes (revision);


CREATE TABLE `knowledge_revisions` (
	`document` VARCHAR(100) NOT NULL COMMENT '逻辑文档标识；同一文档的多个版本共享此值',
	`supplier` VARCHAR(100) NOT NULL COMMENT '政策或指南对应供应商，用于限制检索适用范围',
	`product` VARCHAR(60) NOT NULL COMMENT '供应商下的适用产品代码或目的地，如 standard、上海',
	`language` VARCHAR(10) NOT NULL COMMENT '文档语言标签，当前默认 zh；不表示自动翻译功能',
	`valid_from` VARCHAR(10) NOT NULL COMMENT '版本当前生效起始日期，格式 YYYY-MM-DD',
	`valid_to` VARCHAR(10) NOT NULL COMMENT '版本当前生效截止日期；后续版本发布时可能缩短',
	`original_valid_to` VARCHAR(10) NOT NULL COMMENT '版本最初截止日期；回滚恢复目标版本有效期时使用',
	`status` VARCHAR(20) NOT NULL COMMENT '入库/发布状态：INDEXING、VERIFIED、PUBLISHED、REVOKED、FAILED',
	`digest` VARCHAR(64) NOT NULL COMMENT '正文及业务元数据的 SHA256 指纹；历史记录兼容旧索引摘要，索引配置单独保存在文件清单',
	`rules` JSON NOT NULL COMMENT '明确配置的业务规则 JSON，如 cancel_fee_cents 取消费分值；不是模型猜测的规则',
	`source` VARCHAR(200) NOT NULL COMMENT '原始来源文件名，用于展示证据出处',
	`error` TEXT NOT NULL COMMENT '入库失败的错误类型说明；成功时为空字符串',
	`id` VARCHAR(64) NOT NULL COMMENT '不可变政策版本 ID；新版本由文档标识、正文及业务元数据确定，重建索引保留 ID',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识文档版本及发布清单，管理政策适用范围、有效期和入库状态';


CREATE INDEX ix_knowledge_revisions_document ON knowledge_revisions (document);


CREATE TABLE `operations` (
	`proposal` VARCHAR(64) NOT NULL COMMENT '所属提案 ID，关联 proposals.id',
	`result` JSON NOT NULL COMMENT '已成功提交动作的结构化结果；失败通常返回给 Run，不写入成功账本',
	`id` VARCHAR(64) NOT NULL COMMENT '稳定幂等键，格式为提案 ID:动作序号，序号从 0 开始',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='业务动作执行账本，保存已提交结果并防止重试重复执行';


CREATE TABLE `orders` (
	`owner` VARCHAR(64) NOT NULL COMMENT '订单所属用户 ID，关联 users.id；查询和变更均校验归属',
	`resource` VARCHAR(64) NOT NULL COMMENT '当前预订资源 ID，关联 resources.id；改签可更新',
	`revision` VARCHAR(64) NOT NULL COMMENT '订单冻结的政策版本 ID；取消或改签按此版本核验历史政策',
	`amount` INTEGER NOT NULL COMMENT '订单当前总金额，单位分；不表示真实支付记录，项目未接支付',
	`quantity` INTEGER NOT NULL COMMENT '每个库存槽位的占用数量；航班人数或酒店房间数',
	`slots` JSON NOT NULL COMMENT '订单占用的 inventory.id 列表；取消时据此归还库存',
	`status` VARCHAR(20) NOT NULL COMMENT '订单状态：CONFIRMED 已确认，CANCELLED 已取消',
	`version` INTEGER NOT NULL COMMENT '订单业务版本；改签或取消后递增，执行前核对以阻止过时操作',
	`id` VARCHAR(64) NOT NULL COMMENT '订单唯一标识',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户订单事实表，记录已确认资源、金额、库存占用和订单状态';


CREATE INDEX ix_orders_owner ON orders (owner);


CREATE TABLE `plans` (
	`owner` VARCHAR(64) NOT NULL COMMENT '方案所属用户 ID，关联 users.id',
	`options` JSON NOT NULL COMMENT '候选方案列表 JSON，包括资源、金额、日期、活动安排及知识证据',
	`created` INTEGER NOT NULL COMMENT '方案创建时间，Unix 时间戳，单位秒',
	`id` VARCHAR(64) NOT NULL COMMENT '行程方案唯一标识；审批保存时使用提案 ID',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户确认保存的行程方案表，方案不等于已预订订单';


CREATE TABLE `proposals` (
	`owner` VARCHAR(64) NOT NULL COMMENT '有权确认和执行本提案的用户 ID；后台变更为当前登录管理员',
	`version` INTEGER NOT NULL COMMENT '提案版本；用户确认必须携带相同版本',
	`status` VARCHAR(20) NOT NULL COMMENT '状态：PENDING 待确认、APPROVED 已批准、REJECTED 已拒绝、DONE 全部完成、PARTIAL 部分成功或失败',
	`actions` JSON NOT NULL COMMENT '冻结的动作列表 JSON，包括订单交易、行程保存、工单、修复报告或后台变更内容',
	`evidence` JSON NOT NULL COMMENT '提案附带的政策证据列表，包含节点、版本、出处和正文等',
	`expires` INTEGER NOT NULL COMMENT '提案失效时间，Unix 时间戳，单位秒；过期不能继续按旧内容执行',
	`id` VARCHAR(64) NOT NULL COMMENT '提案唯一标识；图运行中通常使用 run_id，保证重入复用同一提案',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='统一业务变更提案表，冻结待确认动作，批准后才执行正式业务写入';


CREATE TABLE `quotes` (
	`owner` VARCHAR(64) NOT NULL COMMENT '报价所属用户 ID，关联 users.id',
	`resource` VARCHAR(64) NOT NULL COMMENT '本次报价资源 ID，关联 resources.id',
	`resource_version` INTEGER NOT NULL COMMENT '报价生成时的资源版本；执行前与资源当前版本比较',
	`revision` VARCHAR(64) NOT NULL COMMENT '报价适用的政策版本 ID，关联 knowledge_revisions.id',
	`amount` INTEGER NOT NULL COMMENT '本项报价总金额，单位分；已计人数或房间数及住宿晚数',
	`quantity` INTEGER NOT NULL COMMENT '每个库存槽位的占用数；航班为人数，酒店为所需房间数',
	`slots` JSON NOT NULL COMMENT '将占用的 inventory.id 列表；连住酒店包含多晚槽位',
	`expires` INTEGER NOT NULL COMMENT '报价失效时间，Unix 时间戳，单位秒；过期须重新报价确认',
	`id` VARCHAR(64) NOT NULL COMMENT '报价唯一标识，提案动作通过 quote 引用',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='待确认报价快照表，冻结价格、数量、日期库存和政策版本';


CREATE TABLE `resources` (
	`kind` VARCHAR(20) NOT NULL COMMENT '资源类型：flight 航班，hotel 酒店房型',
	`name` VARCHAR(200) NOT NULL COMMENT '面向用户展示的资源名称',
	`supplier` VARCHAR(100) NOT NULL COMMENT '供应商标识，与知识版本 supplier 匹配以确定政策范围',
	`product` VARCHAR(60) NOT NULL COMMENT '供应商下的产品代码，如 economy、standard、flexible',
	`details` JSON NOT NULL COMMENT '资源属性 JSON；航班包含出发地、目的地、日期，酒店包含目的地及每间最大人数',
	`price` INTEGER NOT NULL COMMENT '航班每人或酒店每间每晚的单价，单位为分',
	`version` INTEGER NOT NULL COMMENT '资源价格等业务内容版本；报价执行前核对，防止使用过时报价',
	`id` VARCHAR(64) NOT NULL COMMENT '资源唯一标识，如 flight-0、hotel-0',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='可预订资源表，保存演示航班或酒店商品及当前价格';


CREATE TABLE `run_events` (
	`run` VARCHAR(64) NOT NULL COMMENT '所属运行 ID，关联 runs.id',
	`sequence` INTEGER NOT NULL COMMENT '同一运行内递增的事件序号；与 run 联合唯一，用于 SSE 游标',
	`kind` VARCHAR(30) NOT NULL COMMENT '事件类型，当前包括 progress、approval、result',
	`payload` JSON NOT NULL COMMENT '对应事件的 JSON 内容，包含节点更新、待确认提案或最终结果',
	`id` VARCHAR(64) NOT NULL COMMENT '事件唯一标识',
	PRIMARY KEY (id),
	UNIQUE (run, sequence)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='任务可补读事件流，供 SSE 展示进度、审批和结果并支持断线续传';


CREATE INDEX ix_run_events_run ON run_events (run);


CREATE TABLE `runs` (
	`owner` VARCHAR(64) NOT NULL COMMENT '运行所属用户 ID，关联 users.id；读取、恢复和停止均校验此身份',
	`conversation` VARCHAR(64) NOT NULL COMMENT '所属会话 ID，关联 conversations.id',
	`payload` JSON NOT NULL COMMENT '已校验的结构化 Request 快照，供 worker 重建任务',
	`status` VARCHAR(20) NOT NULL COMMENT '运行状态：QUEUED、RUNNING、WAITING、DONE、FAILED、CANCELLED',
	`resume` JSON COMMENT '用户审批决定及提案版本；恢复时通过 Command(resume=...) 传给图',
	`cancel_requested` INTEGER NOT NULL COMMENT '停止后续任务标记：0 否、1 是；不等同于取消已有订单',
	`lease_until` INTEGER NOT NULL COMMENT '当前 worker 租约截止时间，Unix 时间戳秒；过期运行可被重新领取',
	`fence` INTEGER NOT NULL COMMENT 'worker 领取时递增的令牌；阻止旧 worker 提交过期业务或事件',
	`result` JSON NOT NULL COMMENT '阶段或最终结果 JSON；等待时包含审批提案，完成时包含业务结果',
	`error` TEXT NOT NULL COMMENT '运行异常说明；正常时为空字符串',
	`id` VARCHAR(64) NOT NULL COMMENT '本次运行唯一标识，也是主 LangGraph thread_id',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='后台任务运行表，保存请求、队列状态、审批恢复值及 worker 租约';


CREATE INDEX ix_runs_claim ON runs (status, lease_until);


CREATE TABLE `support_cases` (
	`owner` VARCHAR(64) NOT NULL COMMENT '发起工单的用户 ID，关联 users.id；普通用户只能读取本人记录',
	`request_id` VARCHAR(64) NOT NULL COMMENT '创建请求的稳定标识，通常为 run_id；唯一约束防止重复建单',
	`context` JSON NOT NULL COMMENT '提交工单时冻结的结构化需求及客服结果，用于人工接续处理',
	`status` VARCHAR(20) NOT NULL COMMENT '工单状态：OPEN 待处理、PROCESSING 处理中、CLOSED 已关闭',
	`assigned` VARCHAR(64) COMMENT '领取工单的管理员用户 ID；为空表示尚未领取',
	`replies` JSON NOT NULL COMMENT '回复列表 JSON，每条记录包含回复人 by 和正文 text',
	`id` VARCHAR(64) NOT NULL COMMENT '工单唯一标识',
	PRIMARY KEY (id),
	UNIQUE (request_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='人工客服工单表，保存用户问题上下文、领取人和回复处理记录';


CREATE TABLE `users` (
	`name` VARCHAR(80) NOT NULL COMMENT '登录用户名，表内唯一',
	`password` VARCHAR(200) NOT NULL COMMENT 'PBKDF2-SHA256 密码校验值，格式为盐值:哈希；不是明文密码',
	`role` VARCHAR(20) NOT NULL COMMENT '账户角色：user 普通用户，admin 人工客服及知识管理员',
	`id` VARCHAR(64) NOT NULL COMMENT '用户唯一标识；演示账户使用 alice、bob、admin',
	PRIMARY KEY (id),
	UNIQUE (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='登录用户表，保存账户凭证和普通用户或管理员角色';




CREATE TABLE `checkpoints` (
  `thread_id` varchar(150) NOT NULL COMMENT '框架线程标识；主图为 run_id，客服为用户与会话组合，研究使用独立线程',
  `checkpoint_ns` varchar(2000) NOT NULL DEFAULT '' COMMENT '框架检查点命名空间，用于区分子图等状态范围；根命名空间通常为空',
  `checkpoint_id` varchar(150) NOT NULL COMMENT '本次检查点的框架标识，与线程及命名空间哈希组成主键',
  `parent_checkpoint_id` varchar(150) DEFAULT NULL COMMENT '上一个检查点 ID；首次快照可为空',
  `type` varchar(150) DEFAULT NULL COMMENT '原生表保留的类型字段；当前 saver 直接读写 checkpoint JSON，不使用此字段，通常为空',
  `checkpoint` json NOT NULL COMMENT '框架检查点结构 JSON；大通道值可能另外引用 checkpoint_blobs',
  `metadata` json NOT NULL DEFAULT (_utf8mb4'{}') COMMENT '框架执行元数据 JSON，例如来源、步骤和父级关联；不是业务订单数据',
  `checkpoint_ns_hash` binary(16) NOT NULL COMMENT '命名空间 SHA256 摘要的前 16 字节；用于复合主键，由兼容 saver 写入',
  PRIMARY KEY (`thread_id`,`checkpoint_ns_hash`,`checkpoint_id`),
  KEY `checkpoints_thread_id_idx` (`thread_id`),
  KEY `checkpoints_checkpoint_id_idx` (`checkpoint_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LangGraph 原生检查点快照，持久保存图状态以支持会话延续及中断恢复';


CREATE TABLE `checkpoint_blobs` (
  `thread_id` varchar(150) NOT NULL COMMENT '所属框架线程标识，与 checkpoints.thread_id 对应',
  `checkpoint_ns` varchar(2000) NOT NULL DEFAULT '' COMMENT '所属框架检查点命名空间',
  `channel` varchar(150) NOT NULL COMMENT '状态通道名称，由 LangGraph 管理，例如某个 State 字段',
  `version` varchar(150) NOT NULL COMMENT '通道值版本标识；检查点据此引用正确的状态值',
  `type` varchar(150) NOT NULL COMMENT '通道值序列化类型标签，也可标识空值或缺失值',
  `blob` longblob COMMENT '序列化后的通道值二进制内容；由框架读写，不应手动修改',
  `checkpoint_ns_hash` binary(16) NOT NULL COMMENT '命名空间 SHA256 摘要的前 16 字节，用于复合主键',
  PRIMARY KEY (`thread_id`,`checkpoint_ns_hash`,`channel`,`version`),
  KEY `checkpoint_blobs_thread_id_idx` (`thread_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LangGraph 原生状态通道值，按线程、命名空间、通道及版本保存序列化数据';


CREATE TABLE `checkpoint_writes` (
  `thread_id` varchar(150) NOT NULL COMMENT '所属框架线程标识',
  `checkpoint_ns` varchar(2000) NOT NULL DEFAULT '' COMMENT '所属框架检查点命名空间',
  `checkpoint_id` varchar(150) NOT NULL COMMENT '本次中间写入关联的检查点 ID',
  `task_id` varchar(150) NOT NULL COMMENT '产生该写入的图任务标识，由框架生成',
  `idx` int NOT NULL COMMENT '同一任务的写入序号；框架对部分特殊通道使用保留序号',
  `channel` varchar(150) NOT NULL COMMENT '被更新的通道名称，也可能是框架错误或中断等内部通道',
  `type` varchar(150) DEFAULT NULL COMMENT '写入值的序列化类型标签',
  `blob` longblob NOT NULL COMMENT '序列化后的写入值二进制内容，由框架反序列化',
  `checkpoint_ns_hash` binary(16) NOT NULL COMMENT '命名空间 SHA256 摘要的前 16 字节，用于复合主键',
  `task_path` varchar(2000) NOT NULL DEFAULT '' COMMENT '框架记录的任务执行路径，用于任务及写入关联',
  PRIMARY KEY (`thread_id`,`checkpoint_ns_hash`,`checkpoint_id`,`task_id`,`idx`),
  KEY `checkpoint_writes_thread_id_idx` (`thread_id`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LangGraph 原生节点中间写入记录，支持执行恢复和避免重复处理已完成步骤';


CREATE TABLE `checkpoint_migrations` (
  `v` int NOT NULL COMMENT '已经执行的原生迁移版本号；当前为 0 至 21，setup 根据它避免重复迁移',
  PRIMARY KEY (`v`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LangGraph MySQL 检查点存储的建表迁移版本账本，不保存用户对话';



INSERT INTO `checkpoint_migrations` (`v`) VALUES (0),(1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12),(13),(14),(15),(16),(17),(18),(19),(20),(21);


START TRANSACTION;

INSERT INTO `users` (`id`,`name`,`password`,`role`) VALUES ('alice','alice','9f3bf05e248caa0ad6c98397d3ad2ba0:e23cb628231e9ec5e458aa628bdb6317024bdaa96ff5168fd353aff009d1c459','user');

INSERT INTO `users` (`id`,`name`,`password`,`role`) VALUES ('bob','bob','b200e00e21e208745777e165c04183db:55ae1cc965f616546af1723ed116c16c7c8432007b968628028cd512cf27828b','user');

INSERT INTO `users` (`id`,`name`,`password`,`role`) VALUES ('admin','admin','313c253b45316b6a10e54a6bf8d4d383:4030d252e7224b003cbea0769c23908d0c074ef66f8f2fc741e5467502ae67f4','admin');

SET @travelmate_departure = DATE_ADD(CURRENT_DATE(), INTERVAL 30 DAY);

INSERT INTO `resources` (`id`,`kind`,`name`,`supplier`,`product`,`details`,`price`,`version`)
VALUES ('flight-0','flight','演示航班 0','演示航空','economy',
 JSON_OBJECT('departure','北京','destination','上海','date',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 0 DAY),'%Y-%m-%d')),80000,1);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES ('flight-0','flight-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 0 DAY),'%Y-%m-%d'),6);

INSERT INTO `resources` (`id`,`kind`,`name`,`supplier`,`product`,`details`,`price`,`version`)
VALUES ('hotel-0','hotel','演示酒店 0','演示酒店','standard',
 JSON_OBJECT('destination','上海','max_people',2),30000,1);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 0 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 0 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 1 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 1 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 2 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 2 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 3 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 3 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 4 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 4 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 5 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 5 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 6 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 6 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 7 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 7 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 8 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 8 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 9 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 9 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 10 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 10 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 11 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 11 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 12 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 12 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 13 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 13 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 14 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 14 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-0-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 15 DAY),'%Y-%m-%d')),'hotel-0',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 15 DAY),'%Y-%m-%d'),3);

INSERT INTO `resources` (`id`,`kind`,`name`,`supplier`,`product`,`details`,`price`,`version`)
VALUES ('flight-1','flight','演示航班 1','演示航空','economy',
 JSON_OBJECT('departure','北京','destination','上海','date',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 1 DAY),'%Y-%m-%d')),100000,1);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES ('flight-1','flight-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 1 DAY),'%Y-%m-%d'),6);

INSERT INTO `resources` (`id`,`kind`,`name`,`supplier`,`product`,`details`,`price`,`version`)
VALUES ('hotel-1','hotel','演示酒店 1','演示酒店','flexible',
 JSON_OBJECT('destination','上海','max_people',2),40000,1);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 0 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 0 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 1 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 1 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 2 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 2 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 3 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 3 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 4 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 4 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 5 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 5 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 6 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 6 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 7 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 7 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 8 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 8 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 9 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 9 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 10 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 10 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 11 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 11 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 12 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 12 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 13 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 13 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 14 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 14 DAY),'%Y-%m-%d'),3);

INSERT INTO `inventory` (`id`,`resource`,`day`,`available`) VALUES (CONCAT('hotel-1-',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 15 DAY),'%Y-%m-%d')),'hotel-1',DATE_FORMAT(DATE_ADD(@travelmate_departure, INTERVAL 15 DAY),'%Y-%m-%d'),3);

COMMIT;

-- demo-catalog
SET @demo_start = DATE_ADD(CURDATE(), INTERVAL 1 DAY);
SET @demo_cities = '[{"code": "bj", "name": "北京", "area": "朝阳", "spots": ["故宫周边", "景山公园", "什刹海", "国家博物馆"]}, {"code": "sh", "name": "上海", "area": "黄浦", "spots": ["外滩", "豫园", "徐汇滨江", "上海博物馆"]}, {"code": "gz", "name": "广州", "area": "天河", "spots": ["珠江沿岸", "越秀公园", "沙面", "广东省博物馆"]}, {"code": "sz", "name": "深圳", "area": "福田", "spots": ["莲花山公园", "深圳湾公园", "南头古城", "深圳博物馆"]}, {"code": "hz", "name": "杭州", "area": "上城", "spots": ["西湖周边", "京杭大运河", "南宋御街", "浙江省博物馆"]}, {"code": "cd", "name": "成都", "area": "锦江", "spots": ["人民公园", "浣花溪公园", "宽窄巷子", "成都博物馆"]}, {"code": "cq", "name": "重庆", "area": "渝中", "spots": ["两江沿岸", "鹅岭公园", "山城步道", "重庆中国三峡博物馆"]}, {"code": "xa", "name": "西安", "area": "碑林", "spots": ["城墙周边", "大雁塔周边", "书院门", "陕西历史博物馆"]}, {"code": "nj", "name": "南京", "area": "玄武", "spots": ["玄武湖", "秦淮河沿岸", "老门东", "南京博物院"]}, {"code": "wh", "name": "武汉", "area": "武昌", "spots": ["东湖周边", "汉口江滩", "昙华林", "湖北省博物馆"]}, {"code": "cs", "name": "长沙", "area": "岳麓", "spots": ["湘江沿岸", "岳麓山周边", "太平老街", "湖南博物院"]}, {"code": "xm", "name": "厦门", "area": "思明", "spots": ["环岛路", "筼筜湖", "中山路", "厦门市博物馆"]}, {"code": "qd", "name": "青岛", "area": "市南", "spots": ["栈桥周边", "八大关", "大学路", "青岛市博物馆"]}, {"code": "dl", "name": "大连", "area": "中山", "spots": ["星海湾", "滨海路", "东关街", "大连博物馆"]}, {"code": "km", "name": "昆明", "area": "五华", "spots": ["翠湖", "滇池周边", "昆明老街", "云南省博物馆"]}, {"code": "lj", "name": "丽江", "area": "古城", "spots": ["丽江古城", "黑龙潭周边", "束河古镇", "东巴文化博物馆"]}, {"code": "sy", "name": "三亚", "area": "吉阳", "spots": ["三亚湾", "大东海", "海棠湾", "三亚市博物馆"]}, {"code": "gl", "name": "桂林", "area": "秀峰", "spots": ["漓江沿岸", "榕杉湖", "东西巷", "桂林博物馆"]}, {"code": "hrb", "name": "哈尔滨", "area": "道里", "spots": ["松花江沿岸", "太阳岛周边", "中央大街", "黑龙江省博物馆"]}, {"code": "hk", "name": "海口", "area": "龙华", "spots": ["海口湾", "万绿园", "骑楼老街", "海南省博物馆"]}]';
CREATE TEMPORARY TABLE _demo_days (n INT PRIMARY KEY);
INSERT INTO _demo_days VALUES (0),(1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12),(13),(14),(15),(16),(17),(18),(19),(20),(21),(22),(23),(24),(25),(26),(27),(28),(29),(30),(31),(32),(33),(34),(35),(36),(37),(38),(39),(40),(41),(42),(43),(44),(45),(46),(47),(48),(49),(50),(51),(52),(53),(54),(55),(56),(57),(58),(59),(60),(61),(62),(63),(64),(65),(66),(67),(68),(69),(70),(71),(72),(73),(74),(75),(76),(77),(78),(79),(80),(81),(82),(83),(84),(85),(86),(87),(88),(89);
START TRANSACTION;
INSERT IGNORE INTO resources (id,kind,name,supplier,product,details,price,version)
SELECT CONCAT('demo-flight-',a.code,'-',b.code,'-',DATE_FORMAT(DATE_ADD(@demo_start,INTERVAL d.n DAY),'%Y%m%d'),'-',s.v),
 'flight',CONCAT('演示航空 TM', (a.n-1)*40+(b.n-1)*2+s.v+1000,' ',a.city,'→',b.city),'演示航空','economy',
 JSON_OBJECT('departure',a.city,'destination',b.city,'date',DATE_FORMAT(DATE_ADD(@demo_start,INTERVAL d.n DAY),'%Y-%m-%d'),
 'departure_time',IF(s.v=0,'08:20','17:50'),'cabin','经济舱','demo',CAST('true' AS JSON)),
 25000+MOD((a.n-1)*173+(b.n-1)*97,900)*100+s.v*13000+WEEKDAY(DATE_ADD(@demo_start,INTERVAL d.n DAY))*1500,1
FROM JSON_TABLE(@demo_cities, '$[*]' COLUMNS (n FOR ORDINALITY, code VARCHAR(8) PATH '$.code', city VARCHAR(40) PATH '$.name', area VARCHAR(40) PATH '$.area')) a CROSS JOIN JSON_TABLE(@demo_cities, '$[*]' COLUMNS (n FOR ORDINALITY, code VARCHAR(8) PATH '$.code', city VARCHAR(40) PATH '$.name', area VARCHAR(40) PATH '$.area')) b CROSS JOIN _demo_days d CROSS JOIN (SELECT 0 v UNION ALL SELECT 1) s
WHERE a.n<>b.n AND d.n<60;
INSERT IGNORE INTO resources (id,kind,name,supplier,product,details,price,version)
SELECT CONCAT('demo-hotel-',a.code,'-',LPAD(h.n,2,'0'),'-',IF(s.v=0,'standard','flexible')),
 'hotel',CONCAT(a.city,'·云旅',LPAD(h.n+1,2,'0'),'酒店（',a.area,'店）·',IF(s.v=0,'标准双床房','灵活大床房')),
 '演示酒店',IF(s.v=0,'standard','flexible'),
 JSON_OBJECT('destination',a.city,'district',a.area,'max_people',2,'room_type',IF(s.v=0,'标准双床房','灵活大床房'),
 'breakfast',CAST(IF(MOD(h.n,2)=0,'true','false') AS JSON),'demo',CAST('true' AS JSON)),
 18000+MOD(a.n-1,5)*3000+h.n*4500+s.v*6000,1
FROM JSON_TABLE(@demo_cities, '$[*]' COLUMNS (n FOR ORDINALITY, code VARCHAR(8) PATH '$.code', city VARCHAR(40) PATH '$.name', area VARCHAR(40) PATH '$.area')) a CROSS JOIN _demo_days h CROSS JOIN (SELECT 0 v UNION ALL SELECT 1) s WHERE h.n<10;
INSERT IGNORE INTO inventory (id,resource,day,available)
SELECT id,id,JSON_UNQUOTE(JSON_EXTRACT(details,'$.date')),60 FROM resources WHERE id LIKE 'demo-flight-%';
INSERT IGNORE INTO inventory (id,resource,day,available)
SELECT CONCAT(r.id,'-',DATE_FORMAT(DATE_ADD(@demo_start,INTERVAL d.n DAY),'%Y-%m-%d')),r.id,
 DATE_FORMAT(DATE_ADD(@demo_start,INTERVAL d.n DAY),'%Y-%m-%d'),12
FROM resources r CROSS JOIN _demo_days d WHERE r.id LIKE 'demo-hotel-%';
COMMIT;
DROP TEMPORARY TABLE _demo_days;
