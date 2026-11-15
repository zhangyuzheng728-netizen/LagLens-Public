"""Small, project-local diagnostic skill cards for the AI assistant.

Skills are not plugins and never execute tools.  A skill is a short rule
card injected into the same DeepSeek request only when the current
question (or recent conversation) needs it.
"""

from __future__ import annotations


NETWORK_LOCAL_SKILL_ID = "network_vs_local"

NETWORK_LOCAL_SKILL = (
    "【诊断 Skill｜网络还是本机（可选规则）】\n"
    "只在当前问题或最近对话确实涉及联机延迟、画面停顿或两者区分时使用。"
    "没有关联报告时，只解释怎么区分，不诊断这次表现。\n"
    "1. 先分现象：整个画面没有及时更新，和画面更新稳定但队友瞬移、交互延迟，"
    "是两种线索，也可能同时发生。\n"
    "2. 只按已测证据排优先级：画面稳定、网关和公网探测在同一时段反复波动，"
    "可以先查本地连接，但不能认定 Wi-Fi 或路由器坏了。画面明显停顿、网络探测稳定，"
    "可以先查本机或游戏出帧，但不能排除未测的游戏服务器问题。两边都有异常就分开说明，"
    "不要强行归为同一个原因。\n"
    "3. 没测到就说没测到：公网探测不是游戏内延迟，探测超时不是游戏流量丢包，"
    "帧时间异常也不等于硬件损坏。区分仪器测量、玩家描述和推测。\n"
    "4. 给一个有用的下一步：有足够证据才建议改一项，并说明怎么复测；证据不足时，"
    "只给一个能区分方向的验证动作。正常就说「这次不用改」，不凑建议。"
)

SKILL_TEXT = {
    NETWORK_LOCAL_SKILL_ID: NETWORK_LOCAL_SKILL,
}

_NETWORK_TERMS = (
    "网络",
    "延迟",
    "ping",
    "丢包",
    "瞬移",
    "联机",
    "队友",
    "跳ping",
    "jitter",
    "latency",
    "packet",
    "lag",
    "rubber",
    "断线",
    "掉线",
)

_STUTTER_TERMS = (
    "卡顿",
    "停顿",
    "掉帧",
    "不顺",
    "卡一下",
    "卡住",
    "卡了",
    "stutter",
    "hitch",
    "frame drop",
)

_CONTEXT_TERMS = (
    "哪边",
    "这个",
    "那次",
    "那一下",
    "刚才",
    "还",
    "更",
    "怎么区分",
    "区分",
    "原因",
    "问题",
)

_METRIC_TERMS = (
    "1% low",
    "p95",
    "p99",
    "fps",
    "帧率",
    "帧时间",
    "显示帧",
    "指标",
    "百分位",
)

_METRIC_QUESTION_TERMS = (
    "是什么",
    "什么意思",
    "怎么算",
    "如何计算",
    "代表什么",
    "解释",
)


def _text(value):
    return (value or "").lower()


def _contains_any(text, terms):
    return any(term in text for term in terms)


def _recent_context(history):
    messages = list(history or ())[-6:]
    return " ".join(
        _text(message.get("content"))
        for message in messages
        if isinstance(message, dict)
    )


def select_skills(question, history=(), has_report=False):
    """Return skill IDs needed for this question.

    Metric-definition questions do not load diagnostic rules.  Deictic
    follow-ups such as "那更像哪边？" use the recent conversation, not a
    single character such as "卡".
    """

    text = _text(question)
    context = _recent_context(history)

    metric_question = (
        _contains_any(text, _METRIC_TERMS)
        and _contains_any(text, _METRIC_QUESTION_TERMS)
    )

    if metric_question:
        return ()

    direct = (
        _contains_any(text, _NETWORK_TERMS)
        or _contains_any(text, _STUTTER_TERMS)
    )

    if direct:
        return (NETWORK_LOCAL_SKILL_ID,)

    deictic_follow_up = _contains_any(text, _CONTEXT_TERMS)
    context_has_network = _contains_any(
        context,
        _NETWORK_TERMS,
    )
    context_has_display = _contains_any(
        context,
        _STUTTER_TERMS,
    )

    if (
        deictic_follow_up
        and context_has_network
        and context_has_display
    ):
        return (NETWORK_LOCAL_SKILL_ID,)

    return ()


def skill_block(skill_ids):
    """Render selected rules as one compact optional block."""

    parts = [
        SKILL_TEXT[skill_id]
        for skill_id in skill_ids or ()
        if skill_id in SKILL_TEXT
    ]

    if not parts:
        return ""

    return "\n\n" + "\n\n".join(parts)
