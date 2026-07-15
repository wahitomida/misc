"""Azure OpenAI クライアント (Chat + Embedding). リトライ・バックオフ付き."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

from openai import AzureOpenAI

from .. import config

logger = logging.getLogger(__name__)


@dataclass
class ChatResult:
    text: str
    input_tokens: int
    output_tokens: int
    model: str


class LLMClient:
    """Azure OpenAI 経由の Chat + Embedding (シングルトン)."""

    _instance: "LLMClient | None" = None
    _client: AzureOpenAI | None = None

    def __new__(cls) -> "LLMClient":
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            if not config.AZURE_OPENAI_ENDPOINT or not config.AZURE_OPENAI_API_KEY:
                raise ValueError(
                    "AZURE_OPENAI_ENDPOINT / AZURE_OPENAI_API_KEY が未設定です"
                )
            cls._instance._client = AzureOpenAI(
                azure_endpoint=config.AZURE_OPENAI_ENDPOINT,
                api_key=config.AZURE_OPENAI_API_KEY,
                api_version=config.AZURE_OPENAI_API_VERSION,
                timeout=config.LLM_TIMEOUT_SEC,
            )
            logger.info(
                "Azure OpenAI client initialized (chat=%s, embedding=%s)",
                config.AZURE_OPENAI_DEPLOYMENT_CHAT,
                config.AZURE_OPENAI_DEPLOYMENT_EMBEDDING,
            )
        return cls._instance

    # ---------- Embedding ----------
    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return self._with_retry(self._embed_call, texts=texts)

    def _embed_call(self, texts: list[str]) -> list[list[float]]:
        assert self._client is not None
        resp = self._client.embeddings.create(
            model=config.AZURE_OPENAI_DEPLOYMENT_EMBEDDING,
            input=texts,
        )
        return [item.embedding for item in resp.data]

    # ---------- Chat ----------
    def chat(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float = 0.2,
        response_format: dict | None = None,
        tools: list[dict] | None = None,
        tool_choice: str | None = None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        return self._with_retry(
            self._chat_call,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            temperature=temperature,
            response_format=response_format,
            tools=tools,
            tool_choice=tool_choice,
            max_tokens=max_tokens,
        )

    def _chat_call(
        self,
        system_prompt: str,
        user_prompt: str,
        temperature: float,
        response_format: dict | None,
        tools: list[dict] | None,
        tool_choice: str | None,
        max_tokens: int | None = None,
    ) -> ChatResult:
        assert self._client is not None
        kwargs: dict[str, Any] = {
            "model": config.AZURE_OPENAI_DEPLOYMENT_CHAT,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": temperature,
        }
        if response_format:
            kwargs["response_format"] = response_format
        if tools:
            kwargs["tools"] = tools
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        if max_tokens is not None:
            kwargs["max_tokens"] = max_tokens
        resp = self._client.chat.completions.create(**kwargs)
        msg = resp.choices[0].message
        text = msg.content or ""
        usage = resp.usage
        return ChatResult(
            text=text,
            input_tokens=getattr(usage, "prompt_tokens", 0) if usage else 0,
            output_tokens=getattr(usage, "completion_tokens", 0) if usage else 0,
            model=config.AZURE_OPENAI_DEPLOYMENT_CHAT,
        )

    def chat_with_tools_loop(
        self,
        system_prompt: str,
        user_prompt: str,
        tools: list[dict],
        tool_handler,
        max_iterations: int = 5,
        temperature: float = 0.2,
    ) -> tuple[ChatResult, list[dict]]:
        """tool_calls の自動ループ.

        Returns
        -------
        (最終 ChatResult, [tool_call ログ])
        """
        assert self._client is not None
        messages: list[dict[str, Any]] = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]
        tool_call_log: list[dict] = []
        total_input = 0
        total_output = 0
        final_text = ""

        for itr in range(max_iterations):
            resp = self._with_retry(
                lambda: self._client.chat.completions.create(  # type: ignore[union-attr]
                    model=config.AZURE_OPENAI_DEPLOYMENT_CHAT,
                    messages=messages,
                    tools=tools,
                    tool_choice="auto",
                    temperature=temperature,
                )
            )
            msg = resp.choices[0].message
            if resp.usage:
                total_input += resp.usage.prompt_tokens
                total_output += resp.usage.completion_tokens

            # tool_calls が無ければ完了
            if not msg.tool_calls:
                final_text = msg.content or ""
                break

            # assistant の発話をメッセージに積む
            messages.append(
                {
                    "role": "assistant",
                    "content": msg.content,
                    "tool_calls": [
                        {
                            "id": tc.id,
                            "type": "function",
                            "function": {
                                "name": tc.function.name,
                                "arguments": tc.function.arguments,
                            },
                        }
                        for tc in msg.tool_calls
                    ],
                }
            )
            # 各 tool_call を実行
            for tc in msg.tool_calls:
                name = tc.function.name
                import json
                try:
                    args = json.loads(tc.function.arguments or "{}")
                except json.JSONDecodeError:
                    args = {}
                logger.info("[tool_loop] iter=%d name=%s args_keys=%s", itr + 1, name, list(args.keys()))
                tool_result = tool_handler(name, args)
                tool_call_log.append({"iteration": itr + 1, "name": name, "args": args})
                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": tool_result if isinstance(tool_result, str)
                                  else json.dumps(tool_result, ensure_ascii=False)[:4000],
                    }
                )
                # finish ツールが呼ばれたら強制終了
                if name == "finish":
                    final_text = args.get("final_answer", "") or msg.content or ""
                    return (
                        ChatResult(
                            text=final_text,
                            input_tokens=total_input,
                            output_tokens=total_output,
                            model=config.AZURE_OPENAI_DEPLOYMENT_CHAT,
                        ),
                        tool_call_log,
                    )
        else:
            # 上限到達: 残りメッセージで最終生成
            resp = self._with_retry(
                lambda: self._client.chat.completions.create(  # type: ignore[union-attr]
                    model=config.AZURE_OPENAI_DEPLOYMENT_CHAT,
                    messages=messages + [{
                        "role": "user",
                        "content": "ここまでに収集した情報のみで最終回答を生成してください。",
                    }],
                    temperature=temperature,
                )
            )
            final_text = resp.choices[0].message.content or ""
            if resp.usage:
                total_input += resp.usage.prompt_tokens
                total_output += resp.usage.completion_tokens

        return (
            ChatResult(
                text=final_text,
                input_tokens=total_input,
                output_tokens=total_output,
                model=config.AZURE_OPENAI_DEPLOYMENT_CHAT,
            ),
            tool_call_log,
        )

    # ---------- Retry ----------
    def _with_retry(self, fn, **kwargs) -> Any:
        wait = config.LLM_RETRY_INITIAL_WAIT
        last_err: Exception | None = None
        for attempt in range(1, config.LLM_MAX_RETRIES + 1):
            try:
                return fn(**kwargs) if kwargs else fn()
            except Exception as e:  # noqa: BLE001
                last_err = e
                logger.warning("LLM 呼び出し失敗 attempt=%d/%d: %s", attempt, config.LLM_MAX_RETRIES, e)
                if attempt == config.LLM_MAX_RETRIES:
                    break
                time.sleep(wait)
                wait *= 2
        raise RuntimeError(f"LLM 呼び出し連続失敗 ({config.LLM_MAX_RETRIES}回): {last_err}") from last_err


def get_llm_client() -> LLMClient:
    return LLMClient()
