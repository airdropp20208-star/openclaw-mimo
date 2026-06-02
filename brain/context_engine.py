#!/usr/bin/env python3
"""
Context Engine — Deep Semantic Understanding
============================================
Analyzes full dialogue context to understand:
- Speaker relationships and roles
- Conversation flow and narrative structure
- Cultural references, slang, idioms
- Tone shifts and humor
- Domain-specific terminology
"""

import json
import re
import requests


class ContextEngine:
    """Deep context analysis using LLM reasoning."""
    
    def __init__(self, api_key: str = "", api_base: str = "", model: str = "mimo-v2.5-pro"):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
    
    def analyze(self, full_text: str, source_lang: str, target_lang: str) -> dict:
        """
        Full context analysis of the dialogue.
        Returns rich context object for downstream processing.
        """
        if not self.api_key:
            return self._fallback_analyze(full_text, source_lang)
        
        prompt = f"""Analyze this {source_lang} dialogue for video dubbing. Think deeply about context.

DIALOGUE:
{full_text}

Provide analysis as JSON with these fields:
{{
  "genre": "news|drama|comedy|tutorial|documentary|casual|action|romance|horror",
  "formality": "formal|casual|mixed",
  "speakers": [
    {{"role": "narrator|character|interviewer|interviewee|host|guest", "gender_guess": "male|female|unknown"}}
  ],
  "mood_arc": ["tense", "humorous", "dramatic", etc.],
  "cultural_refs": ["list of cultural references, idioms, slang to watch out for"],
  "terminology": {{"domain": "general|tech|medical|legal|entertainment|gaming", "key_terms": ["important terms"]}},
  "humor_type": "none|wordplay|slapstick|satire|absurd|sarcastic",
  "target_audience": "general|children|adults|elderly",
  "translation_notes": "Key challenges for {target_lang} translation"
}}

Return ONLY the JSON."""

        try:
            result = self._call_llm(prompt)
            # Parse JSON from response
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except Exception as e:
            print(f"  ⚠️ Context analysis failed: {e}")
        
        return self._fallback_analyze(full_text, source_lang)
    
    def cultural_adapt(self, segments: list[dict], target_lang: str = "Vietnamese") -> list[dict]:
        """
        Post-translation cultural adaptation.
        Adjusts translations for cultural relevance.
        """
        if not self.api_key:
            return segments
        
        # Batch segments for efficiency (groups of 20)
        batch_size = 20
        for batch_start in range(0, len(segments), batch_size):
            batch = segments[batch_start:batch_start + batch_size]
            
            numbered = "\n".join(
                f"{i+1}. {s.get('text_vi', s['text'])}" 
                for i, s in enumerate(batch)
            )
            
            prompt = f"""Adapt these {target_lang} translations for natural dubbing.
Keep meaning but make them sound like native {target_lang} speakers would say.
Fix any awkward phrasing, adjust cultural references, ensure conversational flow.

{numbered}

Return ONLY the adapted lines numbered, nothing else."""

            try:
                result = self._call_llm(prompt)
                adapted = []
                for line in result.split("\n"):
                    m = re.match(r"^\d+[.):\s]+\s*(.+)", line.strip())
                    if m:
                        adapted.append(m.group(1).strip())
                
                for i, text in enumerate(adapted):
                    if batch_start + i < len(segments):
                        segments[batch_start + i]["text_vi"] = text
            except:
                pass  # Keep original translations
        
        return segments
    
    def _fallback_analyze(self, text: str, source_lang: str) -> dict:
        """Simple rule-based analysis when LLM is unavailable."""
        # Detect genre from keywords
        text_lower = text.lower()
        genre = "casual"
        if any(w in text_lower for w in ["欢迎", "今天", "大家好", "新闻"]):
            genre = "news"
        elif any(w in text_lower for w in ["哈哈哈", "笑死", "lol", "haha"]):
            genre = "comedy"
        elif any(w in text_lower for w in ["教程", "学习", "如何", "how to"]):
            genre = "tutorial"
        
        return {
            "genre": genre,
            "formality": "formal" if genre == "news" else "casual",
            "speakers": [{"role": "unknown", "gender_guess": "unknown"}],
            "mood_arc": [],
            "cultural_refs": [],
            "terminology": {"domain": "general", "key_terms": []},
            "humor_type": "none",
            "target_audience": "general",
            "translation_notes": "No LLM available for deep analysis",
        }
    
    def _call_llm(self, prompt: str) -> str:
        """Call MiMo API for analysis."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are an expert video dubbing analyst. Respond with precise JSON analysis."},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        }
        
        resp = requests.post(
            f"{self.api_base}/chat/completions",
            headers=headers, json=payload, timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
