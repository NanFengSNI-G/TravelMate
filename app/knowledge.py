import hashlib
import json
import uuid
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from sqlalchemy import select
from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.models import PayloadSchemaType
from llama_index.core import (
    Document,
    SimpleDirectoryReader,
    StorageContext,
    VectorStoreIndex,
)
from llama_index.core import PromptTemplate, get_response_synthesizer
from llama_index.core.ingestion import IngestionPipeline, IngestionCache
from llama_index.core.node_parser import MarkdownNodeParser, SentenceSplitter
from llama_index.core.node_parser import HierarchicalNodeParser, get_leaf_nodes
from llama_index.core.schema import TextNode, NodeWithScore, QueryBundle
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.core.vector_stores import MetadataFilters, MetadataFilter
from llama_index.core.retrievers import AutoMergingRetriever, QueryFusionRetriever
from llama_index.core.llms import MockLLM
from llama_index.readers.file import PDFReader, FlatReader
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.postprocessor.dashscope_rerank import DashScopeRerank
from app.db import sessions
from app.config import settings
from app.models import Revision, Node
from app.encoding import embedding, rag_llm
from app.contracts import Query, Evidence, EvidenceBundle, PolicyMetadata


class Knowledge:
    def __init__(self, client=None, embed=None, collection=None):
        self.client = client or QdrantClient(url=settings().qdrant_url)
        self.aclient = AsyncQdrantClient(url=settings().qdrant_url)
        self.embed = embed or embedding()
        suffix = "fixture" if settings().embed_mode == "fixture" else "live_v3_1024"
        # v2 表示新版索引布局，保留旧集合，不删除已有开发数据。
        self.collection = collection or f"travelmate_policies_v2_{suffix}"
        self.store = QdrantVectorStore(
            collection_name=self.collection, client=self.client, aclient=self.aclient
        )
        self.root = settings().artifact_dir / "knowledge" / self.collection

    def import_document(self, path: Path, metadata: dict):
        metadata = PolicyMetadata.model_validate(metadata).model_dump(mode="json")
        if path.suffix.lower() == ".md":
            # 不先让 MarkdownReader 去掉标题；标题交给 MarkdownNodeParser 解析。
            documents = SimpleDirectoryReader(
                input_files=[str(path)], file_extractor={".md": FlatReader()}
            ).load_data()
        elif path.suffix.lower() == ".pdf":
            documents = PDFReader(return_full_document=True).load_data(file=path)
        else:
            raise ValueError("仅支持 md/pdf")
        text = "\n\n".join(document.text for document in documents)
        if not text.strip():
            raise ValueError("文档为空或需 OCR；PDFReader 不负责扫描件 OCR")
        config = f"native-v2:{self.embed.model_name}:hierarchy-256-64"
        digest = hashlib.sha256(
            (text + json.dumps(metadata, sort_keys=True) + config).encode()
        ).hexdigest()
        rid = str(uuid.uuid5(uuid.NAMESPACE_URL, metadata["document"] + digest))
        with sessions().begin() as s:
            old = s.get(Revision, rid)
            if old and old.status in ("VERIFIED", "PUBLISHED"):
                return {"revision": rid, "cached": True}
            if not old:
                s.add(
                    Revision(
                        id=rid,
                        document=metadata["document"],
                        supplier=metadata["supplier"],
                        product=metadata["product"],
                        valid_from=metadata["valid_from"],
                        valid_to=metadata["valid_to"],
                        original_valid_to=metadata["valid_to"],
                        status="INDEXING",
                        digest=digest,
                        rules=metadata["rules"],
                        source=path.name,
                    )
                )
            else:
                old.status = "INDEXING"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            cache_path = self.root / "ingestion-cache.json"
            cache = (
                IngestionCache.from_persist_path(str(cache_path))
                if cache_path.exists()
                else IngestionCache()
            )
            document = Document(
                id_=rid,
                text=text,
                metadata={
                    "revision": rid,
                    "supplier": metadata["supplier"],
                    "product": metadata["product"],
                    "visibility": "public",
                },
            )
            # 第一级：框架解析 Markdown 结构，包含代码围栏与多级标题处理。
            sections = IngestionPipeline(
                transformations=[MarkdownNodeParser()],
                cache=cache,
            ).run(documents=[document])
            for section in sections:
                # 只是业务展示标签，不负责决定切分边界。
                section.metadata["section"] = (
                    section.text.splitlines()[0].lstrip("# ").strip()
                )
                section.excluded_embed_metadata_keys = list(section.metadata)
                section.excluded_llm_metadata_keys = list(section.metadata)
            # 第二级：框架按 token 长度构建两层关系，兼顾长节与小段。
            hierarchy = HierarchicalNodeParser.from_defaults(
                node_parser_ids=["parent", "leaf"],
                node_parser_map={
                    "parent": SentenceSplitter(chunk_size=256, chunk_overlap=16),
                    "leaf": SentenceSplitter(chunk_size=64, chunk_overlap=8),
                },
            )
            nodes = IngestionPipeline(transformations=[hierarchy], cache=cache).run(
                documents=sections
            )
            leaves = get_leaf_nodes(nodes)
            docstore = SimpleDocumentStore()
            docstore.add_documents(nodes)
            # 只对叶子做嵌入和向量写入，父节点由原生 docstore 保存。
            IngestionPipeline(
                transformations=[self.embed],
                vector_store=self.store,
                cache=cache,
            ).run(nodes=leaves)
            folder = self.root / rid
            folder.mkdir(parents=True, exist_ok=True)
            docstore.persist(str(folder / "docstore.json"))
            for key in ("revision", "supplier", "product", "visibility"):
                self.client.create_payload_index(
                    self.collection, key, PayloadSchemaType.KEYWORD, wait=True
                )
            with sessions().begin() as s:
                for node in nodes:
                    s.merge(
                        Node(
                            id=node.node_id,
                            revision=rid,
                            parent=(
                                node.parent_node.node_id if node.parent_node else None
                            ),
                            section=node.metadata["section"],
                            text=node.text,
                        )
                    )
                s.get(Revision, rid).status = "VERIFIED"
            cache.persist(str(cache_path))
            return {
                "revision": rid,
                "cached": False,
                "nodes": len(nodes),
                "leaves": len(leaves),
            }
        except Exception as exc:
            with sessions().begin() as s:
                s.get(Revision, rid).status = "FAILED"
                s.get(Revision, rid).error = type(exc).__name__
            raise

    def publish(self, rid):
        with sessions().begin() as s:
            row = s.scalar(select(Revision).where(Revision.id == rid).with_for_update())
            if not row or row.status not in ("VERIFIED", "PUBLISHED"):
                raise ValueError("版本未核验")
            # 同一产品的生效区间不允许重叠，新版本需设置新生效日。
            existing = s.scalars(
                select(Revision).where(
                    Revision.document == row.document,
                    Revision.status == "PUBLISHED",
                    Revision.id != rid,
                )
            ).all()
            for old in existing:
                if old.valid_from <= row.valid_to and row.valid_from <= old.valid_to:
                    if row.valid_from <= old.valid_from:
                        raise ValueError("只能向后发布新版本；历史冲突需管理员核查")
                    # 调整的是适用区间；旧正文、规则和 revision ID 不变，老订单仍可引用。
                    old.valid_to = str(
                        date.fromisoformat(row.valid_from) - timedelta(days=1)
                    )
            row.status = "PUBLISHED"

    def revoke(self, rid):
        with sessions().begin() as s:
            row = s.get(Revision, rid)
            if not row:
                raise ValueError("版本不存在")
            row.status = "REVOKED"

    def rollback(self, rid):
        with sessions().begin() as s:
            target = s.scalar(
                select(Revision).where(Revision.id == rid).with_for_update()
            )
            if not target or target.status not in ("PUBLISHED", "REVOKED"):
                raise ValueError("只能回滚到曾发布的版本")
            newer = s.scalars(
                select(Revision)
                .where(
                    Revision.document == target.document,
                    Revision.id != rid,
                    Revision.valid_from >= target.valid_from,
                    Revision.status == "PUBLISHED",
                )
                .with_for_update()
            ).all()
            for row in newer:
                row.status = "REVOKED"
            target.status = "PUBLISHED"
            target.valid_to = target.original_valid_to

    def revisions(self, query):
        with sessions()() as s:
            stmt = select(Revision).where(
                Revision.supplier == query.supplier,
                Revision.product == query.product,
                Revision.status == "PUBLISHED",
            )
            if query.revision_id:
                stmt = stmt.where(Revision.id == query.revision_id)
            else:
                stmt = stmt.where(
                    Revision.valid_from <= str(query.applicable_date),
                    Revision.valid_to >= str(query.applicable_date),
                )
            return list(s.scalars(stmt))

    @lru_cache(maxsize=32)
    def _components(self, rid, top_k=20):
        # 每个不可变 revision 单独加载原生 docstore，避免跨版本父节点混用。
        docstore = SimpleDocumentStore.from_persist_path(
            str(self.root / rid / "docstore.json")
        )
        storage = StorageContext.from_defaults(
            docstore=docstore, vector_store=self.store
        )
        index = VectorStoreIndex.from_vector_store(self.store, embed_model=self.embed)
        dense = index.as_retriever(
            similarity_top_k=top_k,
            filters=MetadataFilters(
                filters=[
                    MetadataFilter(key="revision", value=rid),
                    MetadataFilter(key="visibility", value="public"),
                ]
            ),
        )
        leaves = get_leaf_nodes(list(docstore.docs.values()))
        # 此版 tokenizer 回调已弃用；用框架支持的正则做中文逐字 BM25 基线。
        lexical = BM25Retriever.from_defaults(
            nodes=leaves,
            similarity_top_k=min(top_k, len(leaves)),
            skip_stemming=True,
            language=None,
            token_pattern=r"(?u)[\u4e00-\u9fff]|[a-zA-Z0-9_]+",
        )
        fusion = QueryFusionRetriever(
            [dense, lexical],
            llm=MockLLM(),
            num_queries=1,
            mode="reciprocal_rerank",
            use_async=False,
            similarity_top_k=top_k,
        )
        return storage, dense, lexical, fusion

    def retriever(self, query: Query, mode="hybrid", parent=True, top_k=20):
        allowed = self.revisions(query)
        if len(allowed) != 1:
            raise ValueError("检索器必须绑定唯一适用版本")
        storage, dense, lexical, fusion = self._components(allowed[0].id, top_k)
        retriever = {"default": dense, "sparse": lexical, "hybrid": fusion}[mode]
        return (
            AutoMergingRetriever(retriever, storage, simple_ratio_thresh=0.5)
            if parent
            else retriever
        )

    def retrieve(self, query: Query, mode="hybrid", parent=True, rerank=True):
        revisions = self.revisions(query)
        ids = [revision.id for revision in revisions]
        if not ids:
            return EvidenceBundle(status="INSUFFICIENT", snapshot=[], evidence=[])
        if len(ids) != 1:
            return EvidenceBundle(status="CONFLICTING", snapshot=ids, evidence=[])
        retriever = self.retriever(query, mode, parent)
        hits = retriever.retrieve(query.question)
        if rerank and settings().rerank_mode == "live":
            hits = DashScopeRerank(
                model=settings().rerank_model,
                top_n=5,
                api_key=settings().model_api_key,
            ).postprocess_nodes(hits, query_bundle=QueryBundle(query.question))
        elif settings().rerank_mode not in ("none", "live"):
            raise ValueError("RERANK_MODE 仅 none/live；不再自写词项重排")
        out = []
        with sessions()() as s:
            valid = {revision.id for revision in self.revisions(query)}
            for hit in hits:
                row = s.get(Node, hit.node.node_id)
                if not row or row.revision not in valid:
                    continue
                revision = s.get(Revision, row.revision)
                out.append(
                    Evidence(
                        node_id=row.id,
                        revision_id=row.revision,
                        source=revision.source,
                        section=row.section,
                        text=row.text,
                        score=float(hit.score or 0),
                    )
                )
                if len(out) == 5:
                    break
        return EvidenceBundle(
            status="SUPPORTED" if out else "INSUFFICIENT", snapshot=ids, evidence=out
        )

    def answer(self, question, bundle: EvidenceBundle):
        """业务已核验的证据交给 LlamaIndex 原生 synthesizer 合成答案。"""
        if bundle.status != "SUPPORTED":
            return {
                "answer": "没有足够的适用证据，请转人工核查。",
                "evidence": bundle.model_dump(mode="json"),
            }
        nodes = [
            NodeWithScore(
                node=TextNode(
                    id_=e.node_id,
                    text=e.text,
                    metadata={
                        "node_id": e.node_id,
                        "revision": e.revision_id,
                        "source": e.source,
                    },
                ),
                score=e.score,
            )
            for e in bundle.evidence
        ]
        synthesizer = get_response_synthesizer(
            llm=rag_llm(),
            response_mode="compact",
            text_qa_template=PromptTemplate(
                "仅根据以下证据回答，引用 node_id；不支持的内容说明不足。不得宣称交易成功。\n"
                "证据：{context_str}\n问题：{query_str}\n回答："
            ),
        )
        response = synthesizer.synthesize(question, nodes=nodes)
        return {"answer": str(response), "evidence": bundle.model_dump(mode="json")}


def load_samples(k=None):
    k = k or Knowledge()
    for meta in json.loads(Path("data/policies.json").read_text()):
        result = k.import_document(Path("data") / meta.pop("file"), meta)
        k.publish(result["revision"])
    print("知识样例已发布")


if __name__ == "__main__":
    load_samples()
