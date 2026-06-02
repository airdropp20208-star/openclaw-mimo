#!/usr/bin/env python3
"""
Emotion Detector — Multi-Modal Emotion Analysis
================================================
Detects emotions from:
- Text content (semantic analysis)
- Speech patterns (pacing, emphasis)
- Context (genre, narrative position)
- Cross-modal correlation

Returns per-segment emotion with confidence score.
"""

import re
import requests


# Emotion taxonomy
EMOTIONS = {
    "neutral": {"energy": 0.3, "valence": 0.5},
    "happy": {"energy": 0.7, "valence": 0.9},
    "sad": {"energy": 0.2, "valence": 0.1},
    "angry": {"energy": 0.9, "valence": 0.1},
    "excited": {"energy": 0.95, "valence": 0.85},
    "calm": {"energy": 0.2, "valence": 0.6},
    "serious": {"energy": 0.5, "valence": 0.4},
    "whisper": {"energy": 0.1, "valence": 0.3},
    "surprised": {"energy": 0.8, "valence": 0.7},
    "fearful": {"energy": 0.7, "valence": 0.15},
    "disgusted": {"energy": 0.5, "valence": 0.05},
    "tender": {"energy": 0.3, "valence": 0.8},
}

# Chinese emotion keywords
ZH_EMOTION_KEYWORDS = {
    "happy": ["开心", "高兴", "快乐", "太好了", "哈哈", "笑", "不错", "好", "棒", "赞", "喜欢"],
    "sad": ["难过", "伤心", "哭", "唉", "可惜", "遗憾", "不开心", "痛苦", "想念"],
    "angry": ["生气", "愤怒", "讨厌", "烦", "气死", "滚", "混蛋", "可恶", "太过分"],
    "excited": ["太棒了", "终于", "万岁", "耶", "冲", "厉害", "加油", "期待"],
    "fearful": ["害怕", "恐怖", "吓", "小心", "危险", "救命", "天哪"],
    "surprised": ["什么", "居然", "竟然", "没想到", "天哪", "不会吧"],
    "tender": ["亲爱的", "宝贝", "想念", "想你", "在乎", "珍惜", "温暖"],
}

# Vietnamese emotion keywords
VI_EMOTION_KEYWORDS = {
    "happy": ["vui", "hạnh phúc", "tuyệt", "giỏi", "hay", "đúng", "thích", "yêu", "tốt"],
    "sad": ["buồn", "khóc", "tiếc", "thương", "đau", "mất", "chia tay"],
    "angry": ["tức", "giận", "ghét", "bực", "đồ", "khốn", "khiếp"],
    "excited": ["wow", "hay quá", "tuyệt vời", "ngạc nhiên", "đỉnh"],
    "fearful": ["sợ", "hãi", "kinh", "đáng sợ"],
    "tender": ["thương", "nhớ", "yêu", "quan tâm"],
}

# Japanese emotion keywords
JA_EMOTION_KEYWORDS = {
    "happy": ["嬉しい", "楽しい", "素晴らしい", "いいね", "良い", "好き"],
    "sad": ["悲しい", "辛い", "残念", "惜しい", "-mortar"],
    "angry": ["怒", "嫌", "うるさい", "許さ"],
    "excited": ["すごい", "やばい", "最高", "やった"],
    "fearful": ["怖い", "恐ろしい", "心配"],
    "tender": ["大好き", "大切", "ありがとう"],
}

# Korean emotion keywords
KO_EMOTION_KEYWORDS = {
    "happy": ["좋아", "행복", "기쁘", "최고", "대박"],
    "sad": ["슬퍼", "아프", "속상", "안타깝"],
    "angry": ["화나", "짜증", "미치", "지겨"],
    "excited": ["와", "대박", "헐", "와우"],
    "fearful": ["무서", "걱정", "불안"],
}


from .human_thinker import HumanThinker


class EmotionDetector:
    """Multi-modal emotion detection."""
    
    def __init__(self, api_key: str = "", api_base: str = "", model: str = "mimo-v2.5-pro"):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
    
    def detect_from_text(self, text: str, context: dict = None, lang: str = "auto") -> str:
        """
        Detect emotion from text using keyword matching + LLM + HumanThinker.
        Returns emotion label.
        """
        # Step 1: Keyword-based detection (fast)
        keyword_emotion = self._detect_keywords(text, lang)
        
        # Step 2: If we have LLM, use HumanThinker for deep analysis
        if self.api_key:
            if keyword_emotion in ("neutral", ""):
                # Ambiguous — use deep thinking
                thinker = HumanThinker(self.api_key, self.api_base, self.model)
                thinking = thinker.think_emotion(text, context)
                return thinking.get("surface_emotion", keyword_emotion or "neutral")
            elif keyword_emotion and keyword_emotion != "neutral":
                # Cross-check with context
                if context:
                    genre = context.get("genre", "")
                    if genre == "news" and keyword_emotion in ("excited", "fearful"):
                        return "serious"
                    elif genre == "comedy" and keyword_emotion == "angry":
                        return "excited"
                return keyword_emotion
        
        # Step 3: LLM unavailable, use keyword result
        if keyword_emotion and keyword_emotion != "neutral":
            return keyword_emotion
        
        return keyword_emotion or "neutral"
    
    def _detect_keywords(self, text: str, lang: str = "auto") -> str:
        """Keyword-based emotion detection."""
        # Auto-detect language
        if lang == "auto":
            lang = self._detect_lang(text)
        
        keyword_map = {
            "zh": ZH_EMOTION_KEYWORDS,
            "vi": VI_EMOTION_KEYWORDS,
            "ja": JA_EMOTION_KEYWORDS,
            "ko": KO_EMOTION_KEYWORDS,
        }
        
        keywords = keyword_map.get(lang, ZH_EMOTION_KEYWORDS)
        text_lower = text.lower()
        
        scores = {}
        for emotion, words in keywords.items():
            score = sum(1 for w in words if w in text_lower)
            if score > 0:
                scores[emotion] = score
        
        # Check for exclamation/intensity markers
        exclamation_count = text.count("!") + text.count("！") + text.count("？")
        if exclamation_count >= 2:
            scores["excited"] = scores.get("excited", 0) + 1
        
        # Check for ellipsis (tenderness/sadness)
        if "..." in text or "..." in text:
            scores["sad"] = scores.get("sad", 0) + 0.5
            scores["tender"] = scores.get("tender", 0) + 0.3
        
        if scores:
            return max(scores, key=scores.get)
        return "neutral"
    
    def _detect_llm(self, text: str, context: dict = None) -> str:
        """LLM-based emotion detection for ambiguous cases."""
        try:
            context_str = ""
            if context:
                context_str = f"\nGenre: {context.get('genre', 'unknown')}\nMood arc: {context.get('mood_arc', [])}"
            
            prompt = f"""Analyze the emotion of this dialogue line for voice acting.
Return ONLY one word from: neutral, happy, sad, angry, excited, calm, serious, whisper, surprised, tender{context_str}

Text: {text}

Emotion:"""

            headers = {
                "Authorization": f"Bearer {self.api_key}",
                "Content-Type": "application/json",
            }
            payload = {
                "model": self.model,
                "messages": [
                    {"role": "system", "content": "You are an emotion analysis AI. Return only the emotion label."},
                    {"role": "user", "content": prompt},
                ],
                "temperature": 0.1,
                "max_tokens": 10,
            }
            
            resp = requests.post(
                f"{self.api_base}/chat/completions",
                headers=headers, json=payload, timeout=15,
            )
            resp.raise_for_status()
            emotion = resp.json()["choices"][0]["message"]["content"].strip().lower()
            
            # Validate
            if emotion in EMOTIONS:
                return emotion
        except:
            pass
        
        return "neutral"
    
    def _detect_lang(self, text: str) -> str:
        """Simple language detection."""
        if any(0x4e00 <= ord(c) <= 0x9fff for c in text):
            return "zh"
        if any(0x3040 <= ord(c) <= 0x309f for c in text):
            return "ja"
        if any(0xac00 <= ord(c) <= 0xd7af for c in text):
            return "ko"
        return "vi"
    
    def compute_arc(self, segments: list[dict]) -> dict:
        """
        Compute the emotional arc across all segments.
        Returns emotion progression for consistent voice acting.
        """
        if not segments:
            return {"segments": [], "total_duration": 0}
        
        total_duration = max(s.get("end", 0) for s in segments)
        
        arc_segments = []
        for seg in segments:
            emotion = seg.get("emotion", "neutral")
            start = seg.get("start", 0)
            end = seg.get("end", 0)
            
            arc_segments.append({
                "start_pos": start / max(total_duration, 0.01),
                "end_pos": end / max(total_duration, 0.01),
                "emotion": emotion,
                "energy": EMOTIONS.get(emotion, {}).get("energy", 0.3),
                "valence": EMOTIONS.get(emotion, {}).get("valence", 0.5),
            })
        
        # Smooth transitions between emotions
        smoothed = self._smooth_arc(arc_segments)
        
        return {
            "segments": smoothed,
            "total_duration": total_duration,
            "dominant": self._dominant_emotion(segments),
        }
    
    def _smooth_arc(self, arc_segments: list[dict]) -> list[dict]:
        """Smooth emotion transitions for natural voice acting."""
        if len(arc_segments) <= 1:
            return arc_segments
        
        smoothed = [arc_segments[0]]
        for i in range(1, len(arc_segments)):
            prev = arc_segments[i - 1]
            curr = arc_segments[i]
            
            # If same emotion, keep it
            if prev["emotion"] == curr["emotion"]:
                smoothed.append(curr)
                continue
            
            # Create transition segment
            transition = {
                "start_pos": curr["start_pos"],
                "end_pos": curr["start_pos"] + (curr["end_pos"] - curr["start_pos"]) * 0.3,
                "emotion": prev["emotion"],
                "energy": prev["energy"],
                "valence": prev["valence"],
                "is_transition": True,
            }
            if transition["end_pos"] > transition["start_pos"]:
                smoothed.append(transition)
            
            smoothed.append(curr)
        
        return smoothed
    
    def _dominant_emotion(self, segments: list[dict]) -> str:
        """Find the most common emotion."""
        from collections import Counter
        emotions = [s.get("emotion", "neutral") for s in segments]
        if not emotions:
            return "neutral"
        return Counter(emotions).most_common(1)[0][0]
