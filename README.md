# TravelMate 原生框架参考实现

主入口：[完整教程](../README.md)。先看 [框架职责与迁移](../框架职责审查与迁移指南.md)。完整源码逐文件展示在章节中。

本机 `conda activate travelmate`；MySQL 127.0.0.1:13316/travelmate 与 Qdrant 127.0.0.1:16333 已准备，依赖按 requirements 固定。运行本参考实现时保持本目录；自己学习时保持 TravelMate 项目根目录。

顺序：按模板配置 .env 和 AUTH_SECRET → python -m app.seed → python -m app.knowledge → 不同终端运行 python -m app.worker、uvicorn app.api:app --host 127.0.0.1 --port 18080、frontend 的 npm ci/npm run dev。前端完整代码在第 20/21/28 章。

检查：python -m pip check；python -m pytest -q；python -m scripts.verify_docs；前端 npm run build。测试使用同库随机临时表/同服务临时集合，只清理自己创建的数据，checkpoint 记录保留。

fixture 使用 LlamaIndex 原生 MockEmbedding/MockLLM 与 LangChain ScriptModel，不代表真实语义/Agent质量。live 需账户、SDK区域和模型支持，调用会计费，本次没有执行付费 API。

原生 Docstore/cache 位于 artifacts/knowledge，属于恢复数据；不要删除后宣称 Qdrant 向量完整就能恢复父节点。
