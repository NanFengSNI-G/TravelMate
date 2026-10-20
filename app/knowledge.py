import hashlib
import json
import uuid
from datetime import date, timedelta
from functools import lru_cache
from pathlib import Path
from sqlalchemy import select
from qdrant_client import QdrantClient, AsyncQdrantClient
from qdrant_client.models import PayloadSchemaType, Filter, FieldCondition, MatchValue
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
from llama_index.readers.file import PDFReader, FlatReader
from llama_index.retrievers.bm25 import BM25Retriever
from llama_index.vector_stores.qdrant import QdrantVectorStore
from app.db import sessions
from app.config import settings
from app.models import Revision, Node
from app.encoding import embedding, rag_llm, reranker
from app.contracts import Query, Evidence, EvidenceBundle, PolicyMetadata


def policy_digests(text, metadata):
    canonical = hashlib.sha256(
        json.dumps(
            {"text": text, "metadata": metadata}, sort_keys=True, ensure_ascii=False
        ).encode()
    ).hexdigest()
    compatible = {canonical}
    for version in ("native-v2", "native-v3"):
        for model in ("unknown", "text-embedding-v3", "qwen3.7-text-embedding"):
            config = f"{version}:{model}:hierarchy-256-64"
            compatible.add(
                hashlib.sha256(
                    (text + json.dumps(metadata, sort_keys=True) + config).encode()
                ).hexdigest()
            )
    return canonical, compatible


def choose_policy_revision(rows, canonical):
    published = [row for row in rows if row.status == "PUBLISHED"]
    if len(published) > 1:
        raise ValueError("相同政策存在多个已发布版本，请管理员核查")
    if published:
        return published[0]
    revoked = [row for row in rows if row.status == "REVOKED"]
    if revoked:
        return sorted(revoked, key=lambda row: row.id)[0]
    return next(
        (row for row in rows if row.digest == canonical),
        min(rows, key=lambda row: row.id) if rows else None,
    )


class Knowledge:
    def __init__(self, client=None, embed=None, collection=None):
        self.client = client or QdrantClient(url=settings().qdrant_url)
        self.aclient = AsyncQdrantClient(url=settings().qdrant_url)
        self.embed = embed or embedding()
        self.collection = (
            collection
            or f"travelmate_policies_v3_{settings().embed_model.replace('-', '_').replace('.', '_')}_{settings().embed_dim}"
        )
        self.store = QdrantVectorStore(
            collection_name=self.collection, client=self.client, aclient=self.aclient
        )
        self.root = settings().artifact_dir / "knowledge" / self.collection

    def _index_config(self):
        return {
            "schema": "native-v4",
            "model": self.embed.model_name,
            "dimension": settings().embed_dim,
            "parent_size": 256,
            "parent_overlap": 16,
            "leaf_size": 64,
            "leaf_overlap": 8,
        }

    def _index_ready(self, rid, config):
        folder = self.root / rid
        try:
            manifest = json.loads((folder / "index.json").read_text())
        except (OSError, ValueError):
            return False
        if not isinstance(manifest, dict):
            return False
        if (
            manifest.get("revision") != rid
            or manifest.get("config") != config
            or not (folder / "docstore.json").exists()
            or manifest.get("leaves", 0) <= 0
        ):
            return False
        if not self.client.collection_exists(self.collection):
            return False
        count = self.client.count(
            self.collection,
            count_filter=Filter(
                must=[FieldCondition(key="revision", match=MatchValue(value=rid))]
            ),
            exact=True,
        ).count
        return count >= manifest["leaves"]

    def import_document(self, path: Path, metadata: dict):
        metadata = PolicyMetadata.model_validate(metadata).model_dump(mode="json")
        if path.suffix.lower() == ".md":
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
        digest, compatible = policy_digests(text, metadata)
        config = self._index_config()
        with sessions().begin() as s:
            matches = list(
                s.scalars(
                    select(Revision).where(
                        Revision.document == metadata["document"],
                        Revision.digest.in_(compatible),
                    )
                )
            )
            old = choose_policy_revision(matches, digest)
            rid = (
                old.id
                if old
                else str(uuid.uuid5(uuid.NAMESPACE_URL, metadata["document"] + digest))
            )
            prior_status = old.status if old else "INDEXING"
            if (
                old
                and prior_status in ("VERIFIED", "PUBLISHED", "REVOKED")
                and self._index_ready(rid, config)
            ):
                return {"revision": rid, "cached": True, "status": prior_status}
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
            elif prior_status not in ("VERIFIED", "PUBLISHED", "REVOKED"):
                old.status = "INDEXING"
        try:
            self.root.mkdir(parents=True, exist_ok=True)
            (self.root / rid / "index.json").unlink(missing_ok=True)
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
            sections = IngestionPipeline(
                transformations=[MarkdownNodeParser()],
                cache=cache,
            ).run(documents=[document])
            for section in sections:
                section.metadata["section"] = (
                    section.text.splitlines()[0].lstrip("# ").strip()
                )
                section.excluded_embed_metadata_keys = list(section.metadata)
                section.excluded_llm_metadata_keys = list(section.metadata)
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
                row = s.get(Revision, rid)
                if row.status not in ("PUBLISHED", "REVOKED"):
                    row.status = "VERIFIED"
                row.error = ""
                final_status = row.status
            cache.persist(str(cache_path))
            pending = folder / "index.pending.json"
            pending.write_text(
                json.dumps(
                    {
                        "revision": rid,
                        "config": config,
                        "nodes": len(nodes),
                        "leaves": len(leaves),
                    },
                    ensure_ascii=False,
                )
            )
            pending.replace(folder / "index.json")
            self._components.cache_clear()
            return {
                "revision": rid,
                "cached": False,
                "status": final_status,
                "nodes": len(nodes),
                "leaves": len(leaves),
            }
        except Exception as exc:
            with sessions().begin() as s:
                row = s.get(Revision, rid)
                if prior_status not in ("VERIFIED", "PUBLISHED", "REVOKED"):
                    row.status = "FAILED"
                row.error = type(exc).__name__
            raise

    def publish(self, rid):
        with sessions().begin() as s:
            row = s.scalar(select(Revision).where(Revision.id == rid).with_for_update())
            if not row or row.status not in ("VERIFIED", "PUBLISHED"):
                raise ValueError("版本未核验")
            if row.status == "PUBLISHED":
                return
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
        lexical = BM25Retriever.from_defaults(
            nodes=leaves,
            similarity_top_k=min(top_k, len(leaves)),
            skip_stemming=True,
            language=None,
            token_pattern=r"(?u)[\u4e00-\u9fff]|[a-zA-Z0-9_]+",
        )
        fusion = QueryFusionRetriever(
            [dense, lexical],
            llm=rag_llm(),
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
        if not self._index_ready(allowed[0].id, self._index_config()):
            raise ValueError(
                "该政策尚未完成当前模型的索引构建，请重新执行 python -m app.knowledge"
            )
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
        if rerank:
            hits = reranker(top_n=5).postprocess_nodes(
                hits, query_bundle=QueryBundle(query.question)
            )
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
                "仅根据以下证据用中文简洁回答，在相关句末用方括号引用证据 node_id，不输出字段名。"
                "明确适用产品，不能将一个房型或航班的条款泛化；不支持的内容说明不足。不得宣称交易成功。\n"
                "证据：{context_str}\n问题：{query_str}\n回答："
            ),
        )
        response = synthesizer.synthesize(question, nodes=nodes)
        return {"answer": str(response), "evidence": bundle.model_dump(mode="json")}


def load_samples(k=None, *, all_destinations=True, only_missing=False):
    k = k or Knowledge()
    for meta in json.loads(Path("data/policies.json").read_text()):
        if not all_destinations and meta["document"].startswith("destination-"):
            continue
        if only_missing:
            with sessions()() as session:
                existing = session.scalar(
                    select(Revision).where(
                        Revision.document == meta["document"],
                        Revision.supplier == meta["supplier"],
                        Revision.product == meta["product"],
                        Revision.status.in_(["PUBLISHED", "REVOKED"]),
                    )
                )
            if existing:
                print(
                    f"{meta['document']}: 保留已有 {existing.status} 版本，更新请通过知识管理"
                )
                continue
        result = k.import_document(Path("data") / meta.pop("file"), meta)
        if result["status"] == "REVOKED":
            raise ValueError(f"样例 {meta['document']} 已撤回；初始化不会自动重新发布")
        k.publish(result["revision"])
        print(
            f"{meta['document']}: revision={result['revision']}，索引{'复用' if result['cached'] else '已构建'}"
        )
    print("知识样例初始化完成")


if __name__ == "__main__":
    load_samples(only_missing=True)
