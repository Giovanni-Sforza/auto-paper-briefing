"""
ai_summarizer.py — AI 阅读与总结模块
调用 OpenAI 兼容 API，严格按照预设维度提取客观信息
"""

import time
import json
import logging
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)


# ── 系统 Prompt（核心约束）────────────────────────────────────────────
SYSTEM_PROMPT = """你是一个严格的学术论文信息提取助手。

【核心规则，必须严格遵守】
1. 你的唯一任务是从论文文本中，按照指定维度提取信息并客观罗列。
2. 只允许提取论文中**明确出现**的事实、数据、方法名称和结论。
3. **严禁**做出任何价值判断、优缺点评价，或使用"优秀"、"强大"、"创新"、"不足"等带有主观倾向的词汇。
4. 如果某个维度在论文中找不到相关信息，请填写"论文中未明确提及"，不得推测或补充。
5. 所有输出必须使用**中文**。
6. 输出格式为 JSON，结构见用户请求中的说明。"""


class AISummarizer:
    """调用 AI API 对论文进行客观总结"""

    def __init__(self, config: dict):
        self.api_key = config["ai"]["api_key"]
        self.base_url = config["ai"]["base_url"].rstrip("/")
        self.model = config["ai"]["model"]
        self.temperature = config["ai"]["temperature"]
        self.max_tokens = config["ai"]["max_tokens"]
        self.dimensions = config["summary"]["dimensions"]
        self.max_retries = config["performance"]["max_retries"]
        self.retry_delay = config["performance"]["retry_delay"]
        self.request_interval = config["performance"]["request_interval"]

    def summarize(self, paper: dict, text: str) -> dict:
        """
        对单篇论文生成客观总结
        返回 {维度名: 提取内容} 的字典
        """
        user_prompt = self._build_user_prompt(paper, text)

        for attempt in range(1, self.max_retries + 1):
            try:
                response_text = self._call_api(user_prompt)
                summary = self._parse_response(response_text)
                time.sleep(self.request_interval)
                return summary
            except Exception as e:
                logger.warning(f"    AI API 调用失败 (第{attempt}次): {e}")
                if attempt < self.max_retries:
                    time.sleep(self.retry_delay)
                else:
                    raise RuntimeError(f"AI 总结失败（已重试 {self.max_retries} 次）: {e}")

    def _build_user_prompt(self, paper: dict, text: str) -> str:
        """构建用户 Prompt"""
        dimensions_str = "\n".join(
            f'  "{self._dim_key(dim)}": "<该维度的提取内容>"'
            for dim in self.dimensions
        )

        prompt = f"""请对以下学术论文进行信息提取。

【论文基本信息】
标题: {paper['title']}
作者: {', '.join(paper['authors'][:5])}{'等' if len(paper['authors']) > 5 else ''}
摘要: {paper.get('abstract', '无')}

【论文正文（部分）】
{text}

---

【提取任务】
请严格按照以下维度，从上述文本中提取客观信息。
提取维度及说明：
{chr(10).join(f'- {dim}' for dim in self.dimensions)}

【输出格式要求】
请仅输出一个合法的 JSON 对象，格式如下（不要输出任何 JSON 之外的内容）：
{{
{dimensions_str}
}}"""
        return prompt

    def _dim_key(self, dimension: str) -> str:
        """将维度描述转为简洁的 JSON key（取冒号前的部分）"""
        return dimension.split("：")[0].split(":")[0].strip()

    def _call_api(self, user_prompt: str) -> str:
        """调用 OpenAI 兼容 API"""
        url = f"{self.base_url}/chat/completions"

        payload = {
            "model": self.model,
            "temperature": self.temperature,
            "max_tokens": self.max_tokens,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }

        data = json.dumps(payload).encode("utf-8")
        headers = {
            "Content-Type": "application/json",
            "Authorization": f"Bearer {self.api_key}",
        }

        req = urllib.request.Request(url, data=data, headers=headers, method="POST")

        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            error_body = e.read().decode("utf-8", errors="ignore")
            raise RuntimeError(f"HTTP {e.code}: {error_body[:200]}")

        # 提取回复文本
        content = result["choices"][0]["message"]["content"].strip()
        return content

    def _parse_response(self, response_text: str) -> dict:
        """
        解析 AI 返回的 JSON
        兼容带 markdown 代码块的情况
        """
        # 去除 markdown 代码块
        text = response_text.strip()
        if text.startswith("```"):
            lines = text.split("\n")
            # 去掉首尾的 ``` 行
            text = "\n".join(lines[1:-1] if lines[-1].strip() == "```" else lines[1:])

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            # 尝试找到 JSON 对象范围
            start = text.find("{")
            end = text.rfind("}") + 1
            if start >= 0 and end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass
            # 降级：返回原始文本
            logger.warning("    AI 返回内容不是有效 JSON，以原始文本返回")
            return {"原始总结": response_text}
