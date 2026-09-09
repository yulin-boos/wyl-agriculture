from __future__ import annotations

import json
import http.client
import ipaddress
import os
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any

import yaml


REQUIRED_ADVICE_FIELDS = (
    "summary",
    "immediate_actions",
    "prevention",
    "monitoring",
    "seek_professional_help_when",
    "safety_note",
)


ADVICE_PROVIDER_PRESETS: dict[str, dict[str, object]] = {
    "deepseek": {
        "name": "DeepSeek",
        "base_url": "https://api.deepseek.com",
        "model": "deepseek-v4-flash",
        "description": "深度求索官方兼容接口",
        "request_profile": "deepseek",
        "api_key_env": "DEEPSEEK_API_KEY",
    },
    "qwen": {
        "name": "通义千问",
        "base_url": "https://dashscope.aliyuncs.com/compatible-mode/v1",
        "model": "qwen-plus",
        "description": "阿里云百炼 OpenAI 兼容接口",
        "request_profile": "standard",
        "api_key_env": "DASHSCOPE_API_KEY",
    },
    "zhipu": {
        "name": "智谱 GLM",
        "base_url": "https://open.bigmodel.cn/api/paas/v4",
        "model": "glm-5.2",
        "description": "智谱开放平台兼容接口",
        "request_profile": "standard",
        "api_key_env": "ZHIPU_API_KEY",
    },
    "kimi": {
        "name": "Kimi",
        "base_url": "https://api.moonshot.cn/v1",
        "model": "kimi-k2.5",
        "description": "Kimi 开放平台兼容接口",
        "request_profile": "standard",
        "api_key_env": "MOONSHOT_API_KEY",
    },
    "siliconflow": {
        "name": "硅基流动",
        "base_url": "https://api.siliconflow.cn/v1",
        "model": "Qwen/Qwen2.5-72B-Instruct",
        "description": "SiliconFlow 多模型兼容接口",
        "request_profile": "standard",
        "api_key_env": "SILICONFLOW_API_KEY",
    },
    "custom": {
        "name": "自定义兼容接口",
        "base_url": "",
        "model": "",
        "description": "填写任意公开 HTTPS Chat Completions 兼容接口",
        "request_profile": "standard",
        "api_key_env": "CUSTOM_ADVICE_API_KEY",
    },
}

MODEL_NAME_PATTERN = re.compile(r"^[A-Za-z0-9._:/@+\-]{1,160}$")


class DeepSeekAdviceError(RuntimeError):
    def __init__(self, code: str, message_zh: str) -> None:
        super().__init__(message_zh)
        self.code = code
        self.message_zh = message_zh


@dataclass(frozen=True)
class DeepSeekSettings:
    enabled: bool = True
    base_url: str = "https://api.deepseek.com"
    model: str = "deepseek-v4-flash"
    api_key_env: str = "DEEPSEEK_API_KEY"
    timeout_seconds: float = 45.0
    max_tokens: int = 2500
    temperature: float = 0.2
    provider_id: str = "deepseek"
    provider_name: str = "DeepSeek"
    request_profile: str = "deepseek"

    @classmethod
    def from_yaml(cls, path: Path) -> "DeepSeekSettings":
        payload = yaml.safe_load(path.read_text(encoding="utf-8"))
        values = payload.get("deepseek", {})
        return cls(
            enabled=bool(values.get("enabled", True)),
            base_url=str(values.get("base_url", "https://api.deepseek.com")).rstrip("/"),
            model=str(values.get("model", "deepseek-v4-flash")),
            api_key_env=str(values.get("api_key_env", "DEEPSEEK_API_KEY")),
            timeout_seconds=float(values.get("timeout_seconds", 45)),
            max_tokens=int(values.get("max_tokens", 2500)),
            temperature=float(values.get("temperature", 0.2)),
        )


def provider_catalog() -> list[dict[str, object]]:
    return [
        {
            "id": provider_id,
            "name": str(values["name"]),
            "base_url": str(values["base_url"]),
            "default_model": str(values["model"]),
            "description": str(values["description"]),
            "custom": provider_id == "custom",
        }
        for provider_id, values in ADVICE_PROVIDER_PRESETS.items()
    ]


def _validate_public_https_base_url(value: str) -> str:
    if len(value) > 500:
        raise DeepSeekAdviceError("invalid_base_url", "API 基础地址过长。")
    normalized = value.strip().rstrip("/")
    if normalized.endswith("/chat/completions"):
        normalized = normalized[: -len("/chat/completions")].rstrip("/")
    parsed = urllib.parse.urlsplit(normalized)
    if parsed.scheme.lower() != "https":
        raise DeepSeekAdviceError(
            "insecure_base_url", "自定义 API 必须使用公开的 HTTPS 地址。"
        )
    if not parsed.hostname or parsed.username or parsed.password:
        raise DeepSeekAdviceError("invalid_base_url", "自定义 API 基础地址格式不正确。")
    if parsed.query or parsed.fragment:
        raise DeepSeekAdviceError("invalid_base_url", "API 基础地址不能包含查询参数或片段。")
    hostname = parsed.hostname.rstrip(".").lower()
    if hostname == "localhost" or hostname.endswith(".localhost") or hostname.endswith(".local"):
        raise DeepSeekAdviceError("private_base_url", "自定义 API 不能指向本机或内网地址。")
    try:
        literal_ip = ipaddress.ip_address(hostname)
    except ValueError:
        literal_ip = None
    if literal_ip is not None and not literal_ip.is_global:
        raise DeepSeekAdviceError("private_base_url", "自定义 API 不能指向本机或内网地址。")
    try:
        port = parsed.port or 443
        resolved = socket.getaddrinfo(hostname, port, type=socket.SOCK_STREAM)
    except (OSError, ValueError) as error:
        raise DeepSeekAdviceError("unresolvable_base_url", "无法解析自定义 API 地址。") from error
    for item in resolved:
        resolved_ip = ipaddress.ip_address(item[4][0])
        if not resolved_ip.is_global:
            raise DeepSeekAdviceError(
                "private_base_url", "自定义 API 不能解析到本机或内网地址。"
            )
    return normalized


def settings_for_provider(
    default_settings: DeepSeekSettings,
    provider_id: str | None,
    base_url: str | None = None,
    model: str | None = None,
) -> DeepSeekSettings:
    selected_id = (provider_id or "deepseek").strip().lower()
    preset = ADVICE_PROVIDER_PRESETS.get(selected_id)
    if preset is None:
        raise DeepSeekAdviceError("unknown_provider", "不支持所选 API 厂家。")
    selected_model = (model or str(preset["model"])).strip()
    if not MODEL_NAME_PATTERN.fullmatch(selected_model):
        raise DeepSeekAdviceError("invalid_model", "模型名称格式不正确。")
    if selected_id == "custom":
        selected_base_url = _validate_public_https_base_url(base_url or "")
    else:
        selected_base_url = str(preset["base_url"])
    return replace(
        default_settings,
        base_url=selected_base_url,
        model=selected_model,
        provider_id=selected_id,
        provider_name=str(preset["name"]),
        request_profile=str(preset["request_profile"]),
        api_key_env=str(preset["api_key_env"]),
    )


def resolve_api_key(settings: DeepSeekSettings, explicit_key: str | None = None) -> str:
    key = (explicit_key or os.getenv(settings.api_key_env, "")).strip()
    if not key:
        raise DeepSeekAdviceError(
            "missing_api_key",
            f"未找到 {settings.provider_name} API 密钥，请先在“API 配置”页面填写。",
        )
    if len(key) < 8 or len(key) > 4096 or any(character.isspace() for character in key):
        raise DeepSeekAdviceError(
            "invalid_api_key_format", f"{settings.provider_name} API 密钥格式不正确。"
        )
    if settings.provider_id == "deepseek" and (not key.startswith("sk-") or len(key) < 20):
        raise DeepSeekAdviceError("invalid_api_key_format", "DeepSeek API 密钥格式不正确。")
    return key


def local_review_guidance(diagnosis: dict[str, Any]) -> dict[str, Any]:
    reason = str(diagnosis.get("decision_reason", "low_confidence"))
    quality = diagnosis.get("image_quality", {})
    actions: list[str] = []
    if reason == "image_quality_failed":
        actions.extend(str(message) for message in quality.get("messages_zh", []))
    elif reason == "crop_mismatch_or_unknown":
        actions.extend(
            [
                "重新确认作物种类，检查是否在界面中选错作物。",
                "补拍包含完整叶片、正反面和植株整体的清晰照片。",
                "不要依据当前候选结果直接施药，建议交由当地农技人员复核。",
            ]
        )
    elif reason == "crop_confirmation_required":
        actions.append("请先确认图片中的作物类型，再重新识别。")
    else:
        actions.extend(
            [
                "补拍叶片正面、背面以及植株整体照片，保持自然光和清晰对焦。",
                "记录发病部位、扩散速度、近期天气和用药情况。",
                "在结果确认前隔离明显病叶，避免随意使用农药。",
            ]
        )
    return {
        "source": "local_safety_gate",
        "generated_by_api": False,
        "summary": "当前识别未达到生成病害处置建议的安全条件。",
        "immediate_actions": actions,
        "prevention": ["保持田间通风，避免带病残体在不同地块间传播。"],
        "monitoring": ["未来24至48小时观察症状是否扩展，并保留新照片作对比。"],
        "seek_professional_help_when": [
            "症状快速扩散、成片发生、影响幼苗或果实时，请尽快联系当地农技人员。"
        ],
        "safety_note": "当前结果只用于复核引导，不能据此确定病害或制定用药方案。",
    }


def build_messages(
    diagnosis: dict[str, Any], evidence: list[dict[str, Any]] | None = None
) -> list[dict[str, str]]:
    predictions = diagnosis.get("predictions") or []
    if not predictions:
        raise DeepSeekAdviceError("invalid_diagnosis", "识别结果中没有可供分析的候选信息。")

    accepted = diagnosis.get("decision") == "accepted"
    prediction = predictions[0]
    alternatives = [
        {
            "label": candidate["display_label"],
            "confidence": round(float(candidate["confidence"]), 6),
        }
        for candidate in predictions[1:3]
    ]
    crop_probability_mass = diagnosis.get("crop_probability_mass")
    diagnostic_context = {
        "diagnosis_status": "accepted" if accepted else "needs_review",
        "decision_reason": diagnosis.get("decision_reason", "unknown"),
        "confirmed_crop": prediction.get("crop_zh"),
        "model_disease": prediction.get("disease_zh"),
        "model_label": prediction["label"],
        "confidence": round(float(prediction["confidence"]), 6),
        "crop_probability_mass": (
            round(float(crop_probability_mass), 6)
            if crop_probability_mass is not None
            else None
        ),
        "alternatives": alternatives,
        "image_quality_messages": list(
            diagnosis.get("image_quality", {}).get("messages_zh", [])
        ),
        "user_context": dict(diagnosis.get("user_context") or {}),
        "important": "The configured advice API receives text diagnosis metadata only and has not inspected the image.",
    }
    retrieved_evidence = list(evidence or [])
    diagnostic_context["retrieved_knowledge"] = retrieved_evidence
    common_system = (
        "你是农作物病害辅助决策助手。模型识别结果只是筛查线索，不是实验室确诊。"
        "必须使用简体中文，并只返回一个JSON对象，字段严格为：summary字符串、"
        "immediate_actions字符串数组、prevention字符串数组、monitoring字符串数组、"
        "seek_professional_help_when字符串数组、safety_note字符串。"
        "建议要保守、可执行、适合普通种植者。不得编造地区、季节、药剂登记状态。"
        "user_context中的症状由用户自行填写，未经核验；只能用于调整风险判断和"
        "复查建议，不能单独作为确诊依据。缺失的环境数据不得自行补全或猜测。"
        "不得给出农药商品名、精确剂量、稀释倍数或混配方案；如可能需要化学防治，"
        "只能建议咨询当地农技部门并严格遵循当地登记标签。不得声称已经看过图片。"
        "必须严格参考以下JSON结构示例，不要添加代码块、前言或结尾文字："
        '{"summary":"简要分析","immediate_actions":["处理措施1","处理措施2"],'
        '"prevention":["预防措施1","预防措施2"],'
        '"monitoring":["观察事项1","观察事项2"],'
        '"seek_professional_help_when":["需要专业帮助的情况"],'
        '"safety_note":"安全与复核说明"}'
    )
    if retrieved_evidence:
        common_system += (
            "本次提供了本地知识库检索证据。诊疗分析和措施必须优先依据这些证据，不得编造证据"
            "中不存在的药剂、剂量或事实；建议在相关句末使用方括号标注source_id，例如"
            "[KB-EXAMPLE-001]。只能引用retrieved_knowledge中真实存在的source_id。"
        )
    else:
        common_system += (
            "本次本地知识库没有检索到与第一候选严格匹配的证据，不得声称建议经过RAG知识"
            "检索或虚构来源；只能提供保守的通用措施并建议人工复核。"
        )
    user_context = diagnostic_context["user_context"]
    if user_context:
        common_system += (
            "user_context非空时，summary必须明确区分模型候选与用户自报现场线索。"
            "如果提供了symptom_description，应概括其中最关键的可见症状。"
        )
    if accepted:
        system = common_system
        user = (
            "请根据以下经过安全闸门接受的模型元数据，生成田间处置、预防、观察和求助建议。"
            "summary中要用通俗中文明确给出最可能的病害名称和判断性质，但不要展示内部标签、"
            "候选排名、阈值或原始置信度。仍需明确提醒用户复核。JSON数据如下：\n"
            + json.dumps(diagnostic_context, ensure_ascii=False)
        )
    else:
        system = (
            common_system
            + "当前识别结果未达到安全阈值，不得把任何候选病害当作确诊。可以围绕第一候选病害"
            "给出在等待复核期间即可执行、即使候选有误也不会造成明显伤害的解决方案，例如隔离、"
            "清洁、通风、合理浇水、移除严重病叶和记录症状。每条措施要具体说明怎么做。不得给出"
            "农药名称、剂量、稀释倍数或把化学防治写成确定方案。immediate_actions至少3条，"
            "prevention至少3条，monitoring至少2条。summary要先说明第一候选病害及其典型危害，"
            "同时使用“可能”“疑似”等非确诊措辞。"
        )
        user = (
            "请根据以下未通过安全闸门的模型元数据，先围绕最可能的候选病害给出实用的低风险"
            "解决方案，再给出预防、持续观察、重新拍摄和人工复核建议。候选类别不是确诊结果。"
            "不要自行改写或虚构置信度，程序会单独显示模型概率。JSON数据如下：\n"
            + json.dumps(diagnostic_context, ensure_ascii=False)
        )
    return [{"role": "system", "content": system}, {"role": "user", "content": user}]


def validate_advice(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise DeepSeekAdviceError("invalid_response", "模型接口返回的建议不是JSON对象。")
    missing = [field for field in REQUIRED_ADVICE_FIELDS if field not in payload]
    if missing:
        raise DeepSeekAdviceError(
            "invalid_response", f"模型建议缺少字段：{', '.join(missing)}"
        )
    for field in ("summary", "safety_note"):
        if not isinstance(payload[field], str) or not payload[field].strip():
            raise DeepSeekAdviceError("invalid_response", f"模型返回字段 {field} 无效。")
    for field in (
        "immediate_actions",
        "prevention",
        "monitoring",
        "seek_professional_help_when",
    ):
        if not isinstance(payload[field], list) or not all(
            isinstance(item, str) and item.strip() for item in payload[field]
        ):
            raise DeepSeekAdviceError("invalid_response", f"模型返回字段 {field} 无效。")
    return {field: payload[field] for field in REQUIRED_ADVICE_FIELDS}


def parse_response(response: dict[str, Any]) -> dict[str, Any]:
    try:
        choice = response["choices"][0]
        content = choice["message"]["content"]
    except (KeyError, IndexError, TypeError) as error:
        raise DeepSeekAdviceError("invalid_response", "模型响应缺少建议内容。") from error
    finish_reason = choice.get("finish_reason")
    if finish_reason == "length":
        raise DeepSeekAdviceError(
            "truncated_response", "模型回复超过输出长度限制，JSON被中途截断。"
        )
    if finish_reason == "content_filter":
        raise DeepSeekAdviceError(
            "content_filtered", "模型返回内容被安全策略拦截，请调整图片或稍后重试。"
        )
    if finish_reason == "insufficient_system_resource":
        raise DeepSeekAdviceError(
            "insufficient_system_resource", "模型推理资源暂时不足，请稍后重试。"
        )
    if not isinstance(content, str) or not content.strip():
        raise DeepSeekAdviceError("empty_response", "模型接口没有返回建议内容。")
    stripped = content.strip().lstrip("\ufeff")
    if stripped.startswith("```json") and stripped.endswith("```"):
        stripped = stripped[7:-3].strip()
    elif stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped[3:-3].strip()

    decoder = json.JSONDecoder()
    last_error: json.JSONDecodeError | None = None
    try:
        return validate_advice(json.loads(stripped))
    except json.JSONDecodeError as error:
        last_error = error

    # 容忍“以下是结果”等少量包裹文字，但仍然只接受其中完整、合法的JSON对象。
    for index, character in enumerate(stripped):
        if character != "{":
            continue
        try:
            payload, _ = decoder.raw_decode(stripped[index:])
        except json.JSONDecodeError as error:
            last_error = error
            continue
        return validate_advice(payload)
    raise DeepSeekAdviceError(
        "invalid_json", "模型接口返回的建议无法解析为完整JSON。"
    ) from last_error


def _http_error(status: int, provider_name: str = "DeepSeek") -> DeepSeekAdviceError:
    messages = {
        400: ("invalid_request", f"{provider_name} 请求格式不正确。"),
        401: ("authentication_failed", f"{provider_name} API 密钥无效或已失效。"),
        402: ("insufficient_balance", f"{provider_name} API 账户余额不足。"),
        403: ("permission_denied", f"{provider_name} API 密钥没有调用该模型的权限。"),
        404: ("model_not_found", f"{provider_name} 模型或接口地址不存在。"),
        422: ("invalid_parameters", f"{provider_name} 请求参数不被当前模型支持。"),
        429: ("rate_limited", f"{provider_name} API 请求过于频繁，请稍后重试。"),
        500: ("server_error", f"{provider_name} 服务暂时异常，请稍后重试。"),
        503: ("server_overloaded", f"{provider_name} 服务繁忙，请稍后重试。"),
    }
    code, message = messages.get(
        status, ("http_error", f"{provider_name} 请求失败（HTTP {status}）。")
    )
    return DeepSeekAdviceError(code, message)


class DeepSeekAdviceClient:
    def __init__(self, settings: DeepSeekSettings) -> None:
        self.settings = settings

    def test_connection(self, explicit_api_key: str | None = None) -> dict[str, object]:
        if not self.settings.enabled:
            raise DeepSeekAdviceError("disabled", "API 建议功能已在配置中关闭。")
        api_key = resolve_api_key(self.settings, explicit_api_key)
        request_body: dict[str, object] = {
            "model": self.settings.model,
            "messages": [
                {
                    "role": "user",
                    "content": "这是一次 API 连通性测试。请只回复 OK。",
                }
            ],
            "stream": False,
            "temperature": self.settings.temperature,
            "max_tokens": 16,
        }
        if self.settings.request_profile == "deepseek":
            request_body["thinking"] = {"type": "disabled"}
        request = urllib.request.Request(
            f"{self.settings.base_url}/chat/completions",
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "crop-disease-advice/1.0",
            },
            method="POST",
        )
        started_at = time.perf_counter()
        try:
            with urllib.request.urlopen(
                request, timeout=min(self.settings.timeout_seconds, 25.0)
            ) as response:
                raw = response.read().decode("utf-8")
        except urllib.error.HTTPError as error:
            raise _http_error(error.code, self.settings.provider_name) from error
        except (
            urllib.error.URLError,
            socket.timeout,
            TimeoutError,
            http.client.RemoteDisconnected,
            ConnectionResetError,
        ) as error:
            raise DeepSeekAdviceError(
                "network_error",
                f"无法连接 {self.settings.provider_name}，请检查接口地址或网络。",
            ) from error
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as error:
            raise DeepSeekAdviceError(
                "invalid_response",
                f"{self.settings.provider_name} 已连接，但返回内容不是有效 JSON。",
            ) from error
        if not isinstance(payload, dict) or payload.get("error"):
            raise DeepSeekAdviceError(
                "invalid_response", f"{self.settings.provider_name} 返回了无效的测试响应。"
            )
        if not payload.get("choices") and not payload.get("id"):
            raise DeepSeekAdviceError(
                "invalid_response",
                f"{self.settings.provider_name} 已连接，但响应不兼容 Chat Completions。",
            )
        return {
            "status": "ok",
            "provider": self.settings.provider_name,
            "model": self.settings.model,
            "request_url": request.full_url,
            "latency_ms": round((time.perf_counter() - started_at) * 1000),
        }

    def generate(
        self,
        diagnosis: dict[str, Any],
        explicit_api_key: str | None = None,
        evidence: list[dict[str, Any]] | None = None,
    ) -> dict[str, Any]:
        if not self.settings.enabled:
            raise DeepSeekAdviceError("disabled", "API 建议功能已在配置中关闭。")
        api_key = resolve_api_key(self.settings, explicit_api_key)
        advice_mode = (
            "diagnosis_guidance"
            if diagnosis.get("decision") == "accepted"
            else "review_guidance"
        )
        request_body = {
            "model": self.settings.model,
            "messages": build_messages(diagnosis, evidence=evidence),
            "stream": False,
            "temperature": self.settings.temperature,
            "max_tokens": self.settings.max_tokens,
        }
        if self.settings.request_profile == "deepseek":
            request_body["response_format"] = {"type": "json_object"}
            request_body["thinking"] = {"type": "disabled"}
        request = urllib.request.Request(
            f"{self.settings.base_url}/chat/completions",
            data=json.dumps(request_body, ensure_ascii=False).encode("utf-8"),
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "User-Agent": "crop-disease-advice/1.0",
            },
            method="POST",
        )
        last_error: DeepSeekAdviceError | None = None
        for attempt in range(2):
            try:
                with urllib.request.urlopen(
                    request, timeout=self.settings.timeout_seconds
                ) as response:
                    raw = response.read().decode("utf-8")
                advice = parse_response(json.loads(raw))
                prediction = diagnosis["predictions"][0]
                disease_name = str(prediction.get("disease_zh") or prediction["label"])
                crop_name = str(prediction.get("crop_zh") or "该作物")
                likelihood_percent = round(float(prediction["confidence"]) * 100, 2)
                if advice_mode == "review_guidance":
                    safety_note = (
                        f"当前识别结果未达到安全阈值，模型给出的“{disease_name}”仅是候选线索，"
                        f"尚未经实验室或农技人员确诊。{crop_name}病害类型多样且症状相似，"
                        "请按以下步骤重新拍摄和记录，并联系当地农技部门进行人工复核。"
                    )
                else:
                    safety_note = advice["safety_note"]
                knowledge_sources: list[dict[str, Any]] = []
                seen_source_ids: set[str] = set()
                for item in evidence or []:
                    source_id = str(item.get("source_id", ""))
                    if not source_id or source_id in seen_source_ids:
                        continue
                    seen_source_ids.add(source_id)
                    knowledge_sources.append(
                        {
                            key: item[key]
                            for key in (
                                "source_id",
                                "title",
                                "source_org",
                                "source_url",
                                "retrieval_score",
                            )
                            if key in item
                        }
                    )
                return {
                    "source": f"{self.settings.provider_id}_api",
                    "generated_by_api": True,
                    "provider": self.settings.provider_name,
                    "model": self.settings.model,
                    "advice_mode": advice_mode,
                    **advice,
                    "likely_diagnosis": disease_name,
                    "likelihood_percent": likelihood_percent,
                    "safety_note": safety_note,
                    "rag_used": bool(knowledge_sources),
                    "knowledge_sources": knowledge_sources,
                }
            except DeepSeekAdviceError as error:
                retryable_codes = {
                    "truncated_response",
                    "invalid_json",
                    "invalid_response",
                    "empty_response",
                    "insufficient_system_resource",
                }
                if error.code not in retryable_codes or attempt == 1:
                    raise
                last_error = error
                time.sleep(0.5)
            except urllib.error.HTTPError as error:
                mapped = _http_error(error.code, self.settings.provider_name)
                if error.code not in {429, 500, 503} or attempt == 1:
                    raise mapped from error
                last_error = mapped
                time.sleep(1.0)
            except (
                urllib.error.URLError,
                socket.timeout,
                TimeoutError,
                http.client.RemoteDisconnected,
                ConnectionResetError,
            ) as error:
                mapped = DeepSeekAdviceError(
                    "network_error",
                    f"无法连接 {self.settings.provider_name}，请检查接口地址或稍后重试。",
                )
                if attempt == 1:
                    raise mapped from error
                last_error = mapped
                time.sleep(1.0)
            except json.JSONDecodeError as error:
                raise DeepSeekAdviceError(
                    "invalid_response", f"{self.settings.provider_name} HTTP 响应不是有效JSON。"
                ) from error
        raise last_error or DeepSeekAdviceError(
            "unknown_error", f"{self.settings.provider_name} 建议生成失败。"
        )


def format_advice(advice: dict[str, Any]) -> str:
    likely_diagnosis = advice.get("likely_diagnosis")
    likelihood_percent = advice.get("likelihood_percent")
    sections: list[str] = []
    if likely_diagnosis:
        sections.append(f"最有可能的病症：{likely_diagnosis}")
    if likelihood_percent is not None:
        sections.append(
            f"病症可能性：{float(likelihood_percent):.2f}%（模型候选概率）"
        )
    if sections:
        sections.append("")
    sections.extend([advice["summary"], "", "解决方案："])
    sections.extend(f"- {item}" for item in advice["immediate_actions"])
    sections.extend(["", "预防措施："])
    sections.extend(f"- {item}" for item in advice["prevention"])
    sections.extend(["", "持续观察："])
    sections.extend(f"- {item}" for item in advice["monitoring"])
    sections.extend(["", "需要专业帮助的情况："])
    sections.extend(f"- {item}" for item in advice["seek_professional_help_when"])
    knowledge_sources = advice.get("knowledge_sources") or []
    sections.extend(["", "知识依据："])
    if knowledge_sources:
        for source in knowledge_sources:
            title = source.get("title", "未命名资料")
            organization = source.get("source_org", "")
            url = source.get("source_url", "")
            label = f"{title}（{organization}）" if organization else str(title)
            sections.append(f"- {label}")
            if url:
                sections.append(f"  {url}")
    else:
        sections.append("- 当前本地知识库尚未覆盖该候选病害，本次建议未使用RAG证据。")
    sections.extend(["", f"复核说明：{advice['safety_note']}"])
    return "\n".join(sections)
