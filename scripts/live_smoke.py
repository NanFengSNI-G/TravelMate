# 主动执行才调用付费 API，不读取旧项目的 key。
from app.config import settings
from app.agents import model
from app.encoding import embedding
from app.knowledge import Knowledge
from app.contracts import Query
from datetime import date

assert settings().model_mode == "live" and settings().embed_mode == "live"
assert settings().model_api_key, "先配置你自己的 API key"
print("模型答复:", model().invoke("只回复 TravelMate ready").content)
print("嵌入维度:", len(embedding().get_text_embedding("酒店取消")))
k = Knowledge()
print(
    k.retrieve(
        Query(
            question="标准房取消费用",
            supplier="演示酒店",
            product="standard",
            applicable_date=date.today(),
        )
    ).model_dump_json()
)
