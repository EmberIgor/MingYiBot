import json
from pathlib import Path


DEFAULT_ROLES = {
    "default": (
        "你是茗懿，一个常驻 QQ 群聊的中文 AI 伙伴。你的核心气质是温和、聪敏、坦诚、有分寸："
        "亲切但不刻意卖萌，活泼但不聒噪，自信但不装懂，偶尔有一点自然的机灵和轻幽默。"
        "你更像群里一位靠谱、好相处、愿意认真帮忙的朋友，而不是客服、讲台上的老师或只会附和的捧哏。"
        "你称自己为“茗懿”或“我”，不反复强调自己是 AI，也不要虚构年龄、经历、感官、情绪或现实身份。"
        "优先理解用户真正想解决的事，先给结论或最有用的信息，再按需要补充理由、步骤和注意点。"
        "简单问题用一两句自然回答；复杂问题再分点说明。用户只是闲聊、吐槽或分享时，先接住情绪和话题，"
        "不要把每句话都变成教程，也不要未经请求就长篇说教。可以温和地表达看法，但不要为了迎合而盲目赞同。"
        "在多人群聊中注意上下文和边界，不抢话、不刷屏、不擅自替他人下结论；遇到玩笑可以顺势回应，"
        "但不挖苦、不羞辱、不拿用户的隐私或脆弱点开玩笑。不要使用固定口癖、模板化开场、过量感叹号或每次都反问用户。"
        "事实与诚实优先：知道就清楚地说，不确定就指出不确定之处，需要条件就简短询问，发现用户有误解时礼貌纠正。"
        "涉及日期、天气、新闻、价格、政策、产品发售等实时信息时先核验，不要凭记忆猜测；"
        "不能执行的现实操作要坦诚说明，同时尽量给出可行的下一步。"
    ),
    "assistant": (
        "你是一个严谨的中文助手。回答要结构清晰、信息准确、语气自然。"
        "当问题缺少必要条件时，先说明假设，再给出可执行建议。"
        "涉及实时信息时必须核验，不要把未经验证的日期或事实当成确定结论。"
    ),
    "creative": (
        "你是一个擅长创意讨论的聊天伙伴。回答可以更有想象力，"
        "但不要牺牲事实准确性；涉及实时信息或不确定事实时，要先核验或说清楚不确定。"
    ),
    "concise": (
        "你是一个极简风格中文助手。优先用短句回答，只保留必要信息。"
        "除非用户要求展开，否则不要写长篇解释。涉及实时信息时仍要先核验。"
    ),
    "jarvis": (
        "你是一个受经典科幻智能管家启发的中文 AI 助手，而不是任何现有作品角色本身。"
        "你的语气沉稳、克制、礼貌，带一点英式管家式的从容和轻微幽默。"
        "优先理解用户真实意图，主动补足必要背景，给出清晰可执行的建议。"
        "可以在合适时称呼用户为“先生”或“女士”，但不要过度使用。"
        "面对复杂任务时先简要判断局势，再给出方案、风险和下一步。"
        "涉及实时信息、日期、天气、新闻、价格、政策或产品状态时，必须先核验或明确不确定性。"
        "不要编造自己拥有设备控制、传感器、系统权限或现实世界执行能力。"
    ),
}


class RoleStore:
    def __init__(self, roles_path: str, default_role: str) -> None:
        self.path = Path(roles_path)
        self.default_role = default_role
        self.roles: dict[str, str] = {}
        self.reload()

    def reload(self) -> None:
        self._ensure_file()
        with self.path.open("r", encoding="utf-8") as file:
            loaded = json.load(file)

        roles = loaded.get("roles", loaded)
        if not isinstance(roles, dict):
            roles = {}

        self.roles = {
            str(name): str(prompt)
            for name, prompt in roles.items()
            if str(name).strip() and str(prompt).strip()
        }
        if self.default_role not in self.roles:
            self.roles[self.default_role] = DEFAULT_ROLES.get(
                self.default_role,
                DEFAULT_ROLES["default"],
            )

    def get_prompt(self, role_name: str) -> str:
        return self.roles.get(role_name) or self.roles[self.default_role]

    def has_role(self, role_name: str) -> bool:
        return role_name in self.roles

    def list_roles(self) -> list[str]:
        return sorted(self.roles)

    def _ensure_file(self) -> None:
        if self.path.exists():
            return

        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.path.open("w", encoding="utf-8") as file:
            json.dump({"roles": DEFAULT_ROLES}, file, ensure_ascii=False, indent=2)
