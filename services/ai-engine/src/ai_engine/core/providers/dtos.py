"""
Wire shapes of the model servers the clients in `clients.py` call: the
`*Request` each client sends, and the `*Reply` it validates before reading,
so a malformed reply raises instead of defaulting. Checks that need the
request (rerank index coverage, Jev's pinned model) stay in the client.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --- vLLM requests ---------------------------------------------------------------


class EmbeddingsRequest(BaseModel):
    model: str
    input: str


class RerankRequest(BaseModel):
    model: str
    query: str
    documents: list[str]


class Message(BaseModel):
    role: Literal["system", "user"]
    content: str


class JsonSchema(BaseModel):
    # `schema` would shadow a BaseModel attribute; sent under its wire name.
    model_config = ConfigDict(populate_by_name=True)

    name: str
    schema_: dict[str, Any] = Field(alias="schema")


class ResponseFormat(BaseModel):
    type: Literal["json_schema"] = "json_schema"
    json_schema: JsonSchema


class ChatTemplateKwargs(BaseModel):
    enable_thinking: bool = False


class ChatRequest(BaseModel):
    model: str
    messages: list[Message]
    response_format: ResponseFormat
    # Sampling temperature. The caller sets it: what a task needs (PII NER
    # wants the same answer every time) is the provider's rule, not the client's.
    temperature: float
    chat_template_kwargs: ChatTemplateKwargs = ChatTemplateKwargs()


# --- vLLM replies ----------------------------------------------------------------


class Embedding(BaseModel):
    embedding: list[float]


class EmbeddingsReply(BaseModel):
    data: list[Embedding] = Field(min_length=1)


class RerankResult(BaseModel):
    index: int = Field(ge=0)
    relevance_score: float


class RerankReply(BaseModel):
    results: list[RerankResult]


class ChatMessage(BaseModel):
    content: str


class ChatChoice(BaseModel):
    message: ChatMessage


class ChatReply(BaseModel):
    choices: list[ChatChoice] = Field(min_length=1)


# --- Jev (TypeSafe System One) ----------------------------------------------------


class JevRequest(BaseModel):
    model: str
    state: dict[str, Any]
    questions: dict[str, Any]


class JevAnswer(BaseModel):
    type: Literal["noul"]
    noul: float = Field(ge=0, le=1)


class JevReply(BaseModel):
    model: str
    answers: dict[str, JevAnswer]
