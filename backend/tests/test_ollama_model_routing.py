import unittest
from unittest.mock import AsyncMock, patch

from backend.agents.base import BaseAgent
from backend.llm.ollama_client import chat_json
from frontend.backend.main import RubricSuggestionRequest, suggest_rubric


class _DummyAgent(BaseAgent):
    name = "dummy"

    async def analyze(self, input_data: dict) -> dict:
        return {}


class OllamaModelRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_json_sends_explicit_model_to_ollama_payload(self):
        with patch(
            "backend.llm.ollama_client._do_request",
            new=AsyncMock(return_value={"ok": True}),
        ) as request:
            result = await chat_json(
                system_prompt="Return JSON.",
                user_prompt="{}",
                model="qwen2.5-coder:7b",
                use_cache=False,
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.await_args.args[0]["model"], "qwen2.5-coder:7b")

    async def test_base_agent_routes_llm_calls_to_coder_model_by_default(self):
        agent = _DummyAgent()

        with patch(
            "backend.agents.base.chat_json",
            new=AsyncMock(return_value={"score": 100}),
        ) as chat:
            result = await agent._call_llm(
                system_prompt="Return JSON.",
                user_prompt="{}",
                required_keys=["score"],
            )

        self.assertEqual(result["score"], 100)
        self.assertEqual(chat.await_args.kwargs["model"], "qwen2.5-coder:7b")

    async def test_rubric_suggester_uses_general_model(self):
        payload = {
            "criteria": [
                {
                    "name": "Dogruluk",
                    "description": "Odevin beklenen davranisi karsilamasi",
                    "max_score": 40,
                },
                {
                    "name": "Kod Kalitesi",
                    "description": "Okunabilir ve bakimi kolay cozum",
                    "max_score": 30,
                },
                {
                    "name": "Test",
                    "description": "Temel durumlari kapsayan testler",
                    "max_score": 30,
                },
            ]
        }

        with patch(
            "frontend.backend.main.chat_json",
            new=AsyncMock(return_value=payload),
        ) as chat:
            await suggest_rubric(
                RubricSuggestionRequest(
                    assignment_title="Log ozetleme",
                    assignment_description="Python ile log dosyasindan istatistik cikar.",
                    criterion_count=3,
                )
            )

        self.assertEqual(chat.await_args.kwargs["model"], "qwen2.5:7b")
