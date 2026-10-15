-- TravelMate 完整 MySQL 初始化脚本（MySQL 9.6，2026-10-15）
-- 注意：重新执行会删除 travelmate 的全部旧数据，并删除 travelmate_test。
-- 项目根目录执行：
-- docker exec -i travelmate-mysql sh -c 'MYSQL_PWD="$MYSQL_ROOT_PASSWORD" mysql -uroot --default-character-set=utf8mb4' < travelmate.sql
-- 本脚本由当前教程 reference/app/models.py 与原生 checkpoint 最终结构核对生成。
-- 业务初始数据对应 app/seed.py；SQL 不代替 LlamaIndex 文档解析和向量入库。

SET NAMES utf8mb4;
SET time_zone = '+08:00';
DROP DATABASE IF EXISTS `travelmate_test`;
DROP DATABASE IF EXISTS `travelmate`;
CREATE DATABASE `travelmate` CHARACTER SET utf8mb4 COLLATE utf8mb4_0900_ai_ci;
USE `travelmate`;

-- 阅读约定：COMMENT 会保存到 MySQL，数据库工具中可直接查看表与字段说明。
-- owner/resource/revision 等关联由业务层校验，当前没有声明数据库物理外键。
-- 金额以整数分存储；时间戳以 Unix 秒存储；业务日期使用 YYYY-MM-DD。
-- Python ORM 提供部分默认值；JSON 内部结构见字段注释及对应 Pydantic/业务代码。

-- 一、项目表：金额单位为分；JSON 保存结构化业务数据。
-- ID、版本及部分默认值由 Python ORM 在插入时提供，与 models.py 保持一致。


-- conversations：用户会话表，归属校验并保存意图解析所需的历史请求。
CREATE TABLE `conversations` (
	`owner` VARCHAR(64) NOT NULL COMMENT '所属用户 ID，关联 users.id；服务端用它校验会话归属',
	`history` JSON NOT NULL COMMENT '历史用户文本和结构化 Request 列表；不是完整 Agent 消息或检查点',
	`id` VARCHAR(64) NOT NULL COMMENT '会话唯一标识，关联 runs.conversation',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户会话表，归属校验并保存意图解析所需的历史请求';


CREATE INDEX ix_conversations_owner ON conversations (owner);


-- inventory：按资源及日期记录可用库存，预订占用、取消归还。
CREATE TABLE `inventory` (
	`resource` VARCHAR(64) NOT NULL COMMENT '所属资源 ID，关联 resources.id',
	`day` VARCHAR(10) NOT NULL COMMENT '库存对应日期，格式 YYYY-MM-DD；航班出发日或酒店住宿日',
	`available` INTEGER NOT NULL COMMENT '剩余可售数量；航班为座位数，酒店为该日房间数',
	`id` VARCHAR(64) NOT NULL COMMENT '库存槽位唯一标识；订单 slots 保存这些 ID',
	PRIMARY KEY (id),
	UNIQUE (resource, day)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='按资源及日期记录可用库存，预订占用、取消归还';


-- knowledge_nodes：LlamaIndex 知识节点的 MySQL 正文镜像，用于证据核验和展示。
CREATE TABLE `knowledge_nodes` (
	`revision` VARCHAR(64) NOT NULL COMMENT '所属知识版本 ID，关联 knowledge_revisions.id',
	`parent` VARCHAR(64) COMMENT '父节点 ID；顶层节点为空，完整原生关系同时保存在 Docstore',
	`section` VARCHAR(200) NOT NULL COMMENT '章节展示标签；仅供展示，不由该字段决定切分边界',
	`text` TEXT NOT NULL COMMENT '节点正文；向量由 Qdrant 保存，本字段不是向量',
	`id` VARCHAR(64) NOT NULL COMMENT 'LlamaIndex 节点 ID；检索证据通过该 ID 回查',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LlamaIndex 知识节点的 MySQL 正文镜像，用于证据核验和展示';


CREATE INDEX ix_knowledge_nodes_revision ON knowledge_nodes (revision);


-- knowledge_revisions：知识文档版本及发布清单，管理政策适用范围、有效期和入库状态。
CREATE TABLE `knowledge_revisions` (
	`document` VARCHAR(100) NOT NULL COMMENT '逻辑文档标识；同一文档的多个版本共享此值',
	`supplier` VARCHAR(100) NOT NULL COMMENT '政策或指南对应供应商，用于限制检索适用范围',
	`product` VARCHAR(60) NOT NULL COMMENT '供应商下的适用产品代码或目的地，如 standard、上海',
	`language` VARCHAR(10) NOT NULL COMMENT '文档语言标签，当前默认 zh；不表示自动翻译功能',
	`valid_from` VARCHAR(10) NOT NULL COMMENT '版本当前生效起始日期，格式 YYYY-MM-DD',
	`valid_to` VARCHAR(10) NOT NULL COMMENT '版本当前生效截止日期；后续版本发布时可能缩短',
	`original_valid_to` VARCHAR(10) NOT NULL COMMENT '版本最初截止日期；回滚恢复目标版本有效期时使用',
	`status` VARCHAR(20) NOT NULL COMMENT '入库/发布状态：INDEXING、VERIFIED、PUBLISHED、REVOKED、FAILED',
	`digest` VARCHAR(64) NOT NULL COMMENT '内容、业务元数据和索引配置的 SHA256 摘要，用于版本识别与入库去重',
	`rules` JSON NOT NULL COMMENT '明确配置的业务规则 JSON，如 cancel_fee_cents 取消费分值；不是模型猜测的规则',
	`source` VARCHAR(200) NOT NULL COMMENT '原始来源文件名，用于展示证据出处',
	`error` TEXT NOT NULL COMMENT '入库失败的错误类型说明；成功时为空字符串',
	`id` VARCHAR(64) NOT NULL COMMENT '不可变知识版本 ID，由文档标识及内容、元数据、索引配置摘要确定',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='知识文档版本及发布清单，管理政策适用范围、有效期和入库状态';


CREATE INDEX ix_knowledge_revisions_document ON knowledge_revisions (document);


-- operations：业务动作执行账本，保存已提交结果并防止重试重复执行。
CREATE TABLE `operations` (
	`proposal` VARCHAR(64) NOT NULL COMMENT '所属提案 ID，关联 proposals.id',
	`result` JSON NOT NULL COMMENT '已成功提交动作的结构化结果；失败通常返回给 Run，不写入成功账本',
	`id` VARCHAR(64) NOT NULL COMMENT '稳定幂等键，格式为提案 ID:动作序号，序号从 0 开始',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='业务动作执行账本，保存已提交结果并防止重试重复执行';


-- orders：用户订单事实表，记录已确认资源、金额、库存占用和订单状态。
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


-- plans：用户确认保存的行程方案表，方案不等于已预订订单。
CREATE TABLE `plans` (
	`owner` VARCHAR(64) NOT NULL COMMENT '方案所属用户 ID，关联 users.id',
	`options` JSON NOT NULL COMMENT '候选方案列表 JSON，包括资源、金额、日期、活动安排及知识证据',
	`created` INTEGER NOT NULL COMMENT '方案创建时间，Unix 时间戳，单位秒',
	`id` VARCHAR(64) NOT NULL COMMENT '行程方案唯一标识；审批保存时使用提案 ID',
	PRIMARY KEY (id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='用户确认保存的行程方案表，方案不等于已预订订单';


-- proposals：统一业务变更提案表，冻结待确认动作，批准后才执行正式业务写入。
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


-- quotes：待确认报价快照表，冻结价格、数量、日期库存和政策版本。
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


-- resources：可预订资源表，保存演示航班或酒店商品及当前价格。
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


-- run_events：任务可补读事件流，供 SSE 展示进度、审批和结果并支持断线续传。
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


-- runs：后台任务运行表，保存请求、队列状态、审批恢复值及 worker 租约。
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


-- support_cases：人工客服工单表，保存用户问题上下文、领取人和回复处理记录。
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


-- users：登录用户表，保存账户凭证和普通用户或管理员角色。
CREATE TABLE `users` (
	`name` VARCHAR(80) NOT NULL COMMENT '登录用户名，表内唯一',
	`password` VARCHAR(200) NOT NULL COMMENT 'PBKDF2-SHA256 密码校验值，格式为盐值:哈希；不是明文密码',
	`role` VARCHAR(20) NOT NULL COMMENT '账户角色：user 普通用户，admin 人工客服及知识管理员',
	`id` VARCHAR(64) NOT NULL COMMENT '用户唯一标识；演示账户使用 alice、bob、admin',
	PRIMARY KEY (id),
	UNIQUE (name)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='登录用户表，保存账户凭证和普通用户或管理员角色';


-- 二、LangGraph 原生检查点表。
-- 采用当前 langgraph-checkpoint-mysql 3.0.0 的最终表结构。
-- namespace hash 是普通列，由 TutorialMySQLSaver 使用 SHA2 填入；不使用 MySQL 9.6 已移除的 MD5。


-- checkpoints：LangGraph 原生检查点快照，持久保存图状态以支持会话延续及中断恢复。
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


-- checkpoint_blobs：LangGraph 原生状态通道值，按线程、命名空间、通道及版本保存序列化数据。
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


-- checkpoint_writes：LangGraph 原生节点中间写入记录，支持执行恢复和避免重复处理已完成步骤。
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


-- checkpoint_migrations：LangGraph MySQL 检查点存储的建表迁移版本账本，不保存用户对话。
CREATE TABLE `checkpoint_migrations` (
  `v` int NOT NULL COMMENT '已经执行的原生迁移版本号；当前为 0 至 21，setup 根据它避免重复迁移',
  PRIMARY KEY (`v`)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_0900_ai_ci COMMENT='LangGraph MySQL 检查点存储的建表迁移版本账本，不保存用户对话';


-- 标记原生 saver 的已执行版本，setup() 将核对版本，不会重复 ALTER。

INSERT INTO `checkpoint_migrations` (`v`) VALUES (0),(1),(2),(3),(4),(5),(6),(7),(8),(9),(10),(11),(12),(13),(14),(15),(16),(17),(18),(19),(20),(21);


-- 三、演示初始数据，不插入任何虚构订单、历史会话或执行记录。
-- 三个账户的登录密码均为 tutorial123；存储值为应用兼容的 PBKDF2-SHA256 哈希。
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


-- 四、保留开发连接账号，并清除被删除测试库的旧授权。
-- 不改变已有账号密码；此服务器的 travelmate 用户由 Docker 初始化创建。
GRANT ALL PRIVILEGES ON `travelmate`.* TO 'travelmate'@'%';
-- 使用正式 REVOKE 语句；授权已移除时执行空操作，以便脚本可以再次运行。
SET @travelmate_revoke_test = IF(
    EXISTS(SELECT 1 FROM mysql.db WHERE User='travelmate' AND Host='%' AND Db='travelmate_test'),
    'REVOKE ALL PRIVILEGES ON `travelmate_test`.* FROM ''travelmate''@''%''',
    'DO 0'
);
PREPARE travelmate_revoke_test FROM @travelmate_revoke_test;
EXECUTE travelmate_revoke_test;
DEALLOCATE PREPARE travelmate_revoke_test;

-- 五、执行后的直接核对结果。
SELECT DATABASE() AS database_name, VERSION() AS mysql_version;
SHOW TABLES;
SELECT name, role FROM users ORDER BY name;
SELECT COUNT(*) AS resources FROM resources;
SELECT COUNT(*) AS inventory FROM inventory;
SELECT @travelmate_departure AS departure_date;

