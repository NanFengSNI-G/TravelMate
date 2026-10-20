from llama_index.core.schema import TextNode, NodeWithScore, QueryBundle
from app.config import settings
from app.agents import model
from app.encoding import embedding, reranker, rag_llm


def smoke():
    conf = settings()
    conf.dashscope_api_key
    answer = model().invoke("请只回复 TravelMate ready")
    if not answer.content:
        raise ValueError("主模型没有返回内容")
    vectors = embedding().get_text_embedding_batch(
        ["标准房取消费用为五十元。", "上海目的地交通指南。"]
    )
    if len(vectors) != 2 or any(v is None or len(v) != conf.embed_dim for v in vectors):
        raise ValueError("嵌入服务没有返回两条有效的 1024 维向量")
    query_vector = embedding().get_query_embedding("标准房取消费用")
    if len(query_vector) != conf.embed_dim:
        raise ValueError("查询嵌入维度不正确")
    nodes = [
        NodeWithScore(node=TextNode(text=text))
        for text in ("上海天气与交通。", "标准房取消费用为五十元。")
    ]
    ranked = reranker(top_n=1).postprocess_nodes(
        nodes, query_bundle=QueryBundle("标准房取消多少钱？")
    )
    if len(ranked) != 1 or ranked[0].node.node_id != nodes[1].node.node_id:
        raise ValueError("重排未将直接回答问题的条款排在首位")
    rag_answer = rag_llm().complete(
        "根据证据回答：标准房取消费用为五十元。问题：取消费是多少？"
    )
    if not str(rag_answer).strip():
        raise ValueError("LlamaIndex 回答集成没有返回内容")
    result = {
        "model": conf.model_name,
        "embedding": conf.embed_model,
        "embedding_dimension": len(vectors[0]),
        "rerank": conf.rerank_model,
        "status": "passed",
    }
    print(result)
    return result


if __name__ == "__main__":
    smoke()
