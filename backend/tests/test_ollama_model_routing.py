import unittest
from unittest.mock import AsyncMock, patch

from backend.agents.base import BaseAgent
from backend.core.config import settings
from backend.llm.ollama_client import chat_json, chat_text, get_llm_diagnostics_snapshot
from frontend.backend.main import RubricSuggestionRequest, suggest_rubric


class _DummyAgent(BaseAgent):
    name = "dummy"

    async def analyze(self, input_data: dict) -> dict:
        return {}


class OllamaModelRoutingTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_json_sends_explicit_model_to_ollama_payload(self):
        with (
            patch.object(settings, "llm_provider", "ollama"),
            patch(
                "backend.llm.ollama_client._do_request",
                new=AsyncMock(return_value={"ok": True}),
            ) as request,
        ):
            result = await chat_json(
                system_prompt="Return JSON.",
                user_prompt="{}",
                model="qwen2.5-coder:7b",
                use_cache=False,
            )

        self.assertEqual(result, {"ok": True})
        self.assertEqual(request.await_args.args[0]["model"], "qwen2.5-coder:7b")
        meta = get_llm_diagnostics_snapshot()
        self.assertEqual(meta["provider"], "ollama")
        self.assertEqual(meta["model"], "qwen2.5-coder:7b")
        self.assertEqual(meta["result_status"], "ok")
        self.assertNotIn("user_prompt", meta)

    async def test_chat_json_uses_json_format_for_ollama_schema_hint(self):
        schema_hint = {"ok": True}
        with (
            patch.object(settings, "llm_provider", "ollama"),
            patch(
                "backend.llm.ollama_client._do_request",
                new=AsyncMock(return_value={"ok": True}),
            ) as request,
        ):
            result = await chat_json(
                system_prompt="Return JSON.",
                user_prompt="{}",
                schema_hint=schema_hint,
                model="qwen2.5-coder:7b",
                use_cache=False,
            )

        self.assertEqual(result, {"ok": True})
        payload = request.await_args.args[0]
        self.assertEqual(payload["format"], "json")

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
        self.assertEqual(result["llm_status"], "ok")
        self.assertEqual(result["guardrail_flags"], [])
        self.assertEqual(chat.await_args.kwargs["model"], "qwen2.5-coder:7b")

    async def test_base_agent_marks_repaired_required_key_responses(self):
        agent = _DummyAgent()

        with patch(
            "backend.agents.base.chat_json",
            new=AsyncMock(side_effect=[{"score": 70}, {"summary": "Tamamlandi"}]),
        ):
            result = await agent._call_llm(
                system_prompt="Return JSON.",
                user_prompt="{}",
                required_keys=["score", "summary"],
            )

        self.assertEqual(result["score"], 70)
        self.assertEqual(result["summary"], "Tamamlandi")
        self.assertEqual(result["llm_status"], "repaired")
        self.assertIn("missing_required_keys_repair", result["guardrail_flags"])

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

    async def test_chat_json_routes_coder_model_to_nvidia_nim_payload(self):
        with (
            patch.object(settings, "llm_provider", "nvidia_nim", create=True),
            patch.object(settings, "llm_coder_provider", "nvidia_nim", create=True),
            patch.object(settings, "nvidia_nim_api_key", "secret-key", create=True),
            patch.object(settings, "nvidia_nim_coder_model", "qwen/qwen2.5-coder-32b-instruct", create=True),
            patch.object(settings, "nvidia_nim_num_predict", 3072, create=True),
            patch(
                "backend.llm.ollama_client._do_nvidia_nim_request",
                new=AsyncMock(return_value={"ok": True}),
                create=True,
            ) as request,
        ):
            result = await chat_json(
                system_prompt="Return JSON.",
                user_prompt='{"code":"print(1)"}',
                model=settings.ollama_coder_model,
                use_cache=False,
            )

        self.assertEqual(result, {"ok": True})
        payload = request.await_args.args[0]
        self.assertEqual(payload["model"], "qwen/qwen2.5-coder-32b-instruct")
        self.assertEqual(payload["response_format"], {"type": "json_object"})
        self.assertEqual(payload["messages"][0]["role"], "system")
        self.assertEqual(payload["messages"][1]["role"], "user")
        self.assertEqual(payload["max_tokens"], 3072)

    async def test_chat_json_keeps_explicit_nvidia_nim_token_limit(self):
        with (
            patch.object(settings, "llm_provider", "nvidia_nim", create=True),
            patch.object(settings, "llm_general_provider", "nvidia_nim", create=True),
            patch.object(settings, "nvidia_nim_api_key", "secret-key", create=True),
            patch.object(settings, "nvidia_nim_num_predict", 3072, create=True),
            patch(
                "backend.llm.ollama_client._do_nvidia_nim_request",
                new=AsyncMock(return_value={"ok": True}),
                create=True,
            ) as request,
        ):
            await chat_json(
                system_prompt="Return JSON.",
                user_prompt="{}",
                num_predict=128,
                use_cache=False,
            )

        self.assertEqual(request.await_args.args[0]["max_tokens"], 128)

    async def test_chat_text_routes_to_nvidia_nim_payload(self):
        with (
            patch.object(settings, "llm_provider", "nvidia_nim", create=True),
            patch.object(settings, "llm_general_provider", "nvidia_nim", create=True),
            patch.object(settings, "nvidia_nim_api_key", "secret-key", create=True),
            patch.object(settings, "nvidia_nim_general_model", "qwen/qwen2.5-coder-32b-instruct", create=True),
            patch(
                "backend.llm.ollama_client._do_nvidia_nim_text_request",
                new=AsyncMock(return_value="Merhaba"),
                create=True,
            ) as request,
        ):
            result = await chat_text(
                [{"role": "user", "content": "Kisa cevap ver."}],
                model=settings.ollama_general_model,
            )

        self.assertEqual(result, "Merhaba")
        payload = request.await_args.args[0]
        self.assertEqual(payload["model"], "qwen/qwen2.5-coder-32b-instruct")
        self.assertEqual(payload["messages"][0]["content"], "Kisa cevap ver.")

    async def test_nvidia_nim_mode_without_api_key_returns_none(self):
        with (
            patch.object(settings, "llm_provider", "nvidia_nim", create=True),
            patch.object(settings, "llm_general_provider", "", create=True),
            patch.object(settings, "llm_coder_provider", "", create=True),
            patch.object(settings, "nvidia_nim_api_key", "", create=True),
            patch(
                "backend.llm.ollama_client._do_nvidia_nim_request",
                new=AsyncMock(return_value={"ok": True}),
                create=True,
            ) as request,
        ):
            result = await chat_json(
                system_prompt="Return JSON.",
                user_prompt="{}",
                use_cache=False,
            )

        self.assertIsNone(result)
        request.assert_not_awaited()
        meta = get_llm_diagnostics_snapshot()
        self.assertEqual(meta["provider"], "nvidia_nim")
        self.assertEqual(meta["result_status"], "skipped")
        self.assertEqual(meta["fallback_reason"], "missing_api_key")

    async def test_hybrid_provider_routes_general_to_nim_and_coder_to_ollama(self):
        with (
            patch.object(settings, "llm_provider", "nvidia_nim", create=True),
            patch.object(settings, "llm_general_provider", "nvidia_nim", create=True),
            patch.object(settings, "llm_coder_provider", "ollama", create=True),
            patch.object(settings, "nvidia_nim_api_key", "secret-key", create=True),
            patch(
                "backend.llm.ollama_client._do_nvidia_nim_request",
                new=AsyncMock(return_value={"general": True}),
                create=True,
            ) as nim_request,
            patch(
                "backend.llm.ollama_client._do_request",
                new=AsyncMock(return_value={"coder": True}),
            ) as ollama_request,
        ):
            general = await chat_json(
                system_prompt="Return JSON.",
                user_prompt="{}",
                model=settings.ollama_general_model,
                use_cache=False,
            )
            coder = await chat_json(
                system_prompt="Return JSON.",
                user_prompt="{}",
                model=settings.ollama_coder_model,
                use_cache=False,
            )

        self.assertEqual(general, {"general": True})
        self.assertEqual(coder, {"coder": True})
        self.assertEqual(nim_request.await_count, 1)
        self.assertEqual(ollama_request.await_count, 1)
        self.assertEqual(ollama_request.await_args.args[0]["model"], settings.ollama_coder_model)
