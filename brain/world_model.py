#!/usr/bin/env python3
"""
World Model — Causal Reasoning + Cultural Commonsense
=====================================================
Understands HOW THE WORLD WORKS, not just patterns:
- Causal chains: "betrayal → anger → desire for revenge"
- Cultural commonsense: Chinese humor ≠ Vietnamese humor
- Social dynamics: hierarchy, relationships, power
- Emotional causality: WHY someone feels something
- Domain knowledge: gaming, drama, news, cooking, etc.

This is what makes translations MEAN something vs just being words.
"""

import json
import re
import requests


# ─── Causal Knowledge Base ──────────────────────────────────────────
EMOTION_CAUSALITY = {
    "anger": {
        "causes": ["betrayal", "injustice", "frustration", "humiliation", "threat", "loss"],
        "leads_to": ["revenge", "confrontation", "withdrawal", "tears"],
        "body_language": ["clenched fists", "raised voice", "tense shoulders"],
        "voice_quality": ["loud", "sharp", "trembling"],
    },
    "sadness": {
        "causes": ["loss", "rejection", "failure", "loneliness", "nostalgia", "helplessness"],
        "leads_to": ["crying", "withdrawal", "seeking comfort", "anger"],
        "body_language": ["downcast eyes", "slumped posture", "slow movement"],
        "voice_quality": ["soft", "breaking", "whispery", "monotone"],
    },
    "joy": {
        "causes": ["success", "reunion", "surprise", "love", "achievement", "humor"],
        "leads_to": ["laughter", "sharing", "celebration", "generosity"],
        "body_language": ["smiling", "open posture", "energetic movement"],
        "voice_quality": ["bright", "varied pitch", "fast pace", "warm"],
    },
    "fear": {
        "causes": ["danger", "unknown", "threat", "trauma", "vulnerability"],
        "leads_to": ["flight", "freeze", "fight", "seeking protection"],
        "body_language": ["wide eyes", "tense body", "retreating"],
        "voice_quality": ["high pitch", "fast", "breathy", "trembling"],
    },
}

CULTURAL_PATTERNS = {
    "chinese": {
        "humor_style": ["wordplay", "self-deprecation", "absurd situations", "irony"],
        "emotional_expression": "indirect — often through actions not words",
        "hierarchy": "strong — respect for elders, authority figures",
        "taboo": ["death", "separation", "number 4"],
        "common_refs": {
            "三国": "Romance of Three Kingdoms — loyalty, betrayal, strategy",
            "西游记": "Journey to the West — perseverance, humor, loyalty",
            "面子": "Face — social reputation, very important",
            "关系": "Guanxi — relationships, networking, obligations",
        },
    },
    "vietnamese": {
        "humor_style": ["situational", "wordplay", "self-deprecation", "exaggeration"],
        "emotional_expression": "moderate — culture of restraint but deep feeling",
        "hierarchy": "strong — age-based respect, formal language",
        "taboo": ["death", "ghosts", "taboo words during Tet"],
        "translation_preferences": {
            "keep_original_names": True,
            "translate_proverbs": "find Vietnamese equivalent, not literal",
            "humor": "recreate the joke in Vietnamese style",
            "slang": "use current Vietnamese youth slang for casual scenes",
        },
    },
    "japanese": {
        "humor_style": ["puns", "slapstick", "tsukkomi/boke", "deadpan"],
        "emotional_expression": "very indirect — much left unsaid",
        "hierarchy": "very strong — keigo (honorific language)",
        "common_refs": {
            "あはは": "genuine laughter",
            "すみません": "can mean sorry OR excuse me OR thank you",
        },
    },
    "korean": {
        "humor_style": ["wordplay", "physical", "hierarchical humor"],
        "emotional_expression": "expressive — crying openly is acceptable",
        "hierarchy": "very strong — age determines speech level",
    },
}


class WorldModel:
    """Causal reasoning + cultural commonsense knowledge base."""
    
    def __init__(self, api_key: str = "", api_base: str = "", model: str = "mimo-v2.5-pro"):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self._cache = {}  # Cache LLM queries
    
    def understand_cause(self, text: str, source_lang: str, context: dict = None) -> dict:
        """
        Understand WHY the speaker says/feels this.
        Causal reasoning: what led to this moment?
        """
        cache_key = f"cause_{hash(text)}"
        if cache_key in self._cache:
            return self._cache[cache_key]
        
        # Rule-based first (fast)
        cause_info = self._rule_cause(text, source_lang)
        
        # Enhance with LLM if available
        if self.api_key and cause_info.get("confidence", 0) < 0.7:
            llm_cause = self._llm_cause(text, source_lang, context)
            if llm_cause:
                cause_info.update(llm_cause)
        
        self._cache[cache_key] = cause_info
        return cause_info
    
    def _rule_cause(self, text: str, lang: str) -> dict:
        """Fast rule-based causal analysis."""
        text_lower = text.lower()
        
        # Detect emotion and its likely cause
        detected_emotion = "neutral"
        likely_cause = "unknown"
        expected_reaction = "continue"
        
        for emotion, data in EMOTION_CAUSALITY.items():
            # Check if any cause keywords match
            for cause in data["causes"]:
                if cause in text_lower:
                    detected_emotion = emotion
                    likely_cause = cause
                    expected_reaction = data["leads_to"][0] if data["leads_to"] else "continue"
                    break
        
        return {
            "emotion": detected_emotion,
            "likely_cause": likely_cause,
            "expected_reaction": expected_reaction,
            "confidence": 0.6 if detected_emotion != "neutral" else 0.3,
        }
    
    def _llm_cause(self, text: str, lang: str, context: dict = None) -> dict:
        """LLM-based causal analysis for complex cases."""
        try:
            prompt = f"""Analyze the CAUSAL CHAIN behind this dialogue line.
Why does the speaker feel/say this? What led to this moment?

Text ({lang}): "{text}"
Context: {json.dumps(context or {}, default=str)[:300]}

Return JSON:
{{
  "cause_chain": "what happened before → what they feel now",
  "speaker_intent": "what they want to achieve by saying this",
  "emotional_root": "the deep emotion underneath the surface",
  "social_context": "power dynamics, relationships at play",
  "voice_direction": "how this should sound when spoken"
}}"""
            
            result = self._call_llm(prompt, 0.3)
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        return {}
    
    def bridge_culture(self, text: str, source_lang: str, target_lang: str, context: dict = None) -> dict:
        """
        Find the cultural bridge between source and target.
        What would confuse a Vietnamese viewer watching Chinese content?
        """
        source_key = source_lang.lower().split()[0]  # "Chinese" -> "chinese"
        target_key = target_lang.lower().split()[0]
        
        source_culture = CULTURAL_PATTERNS.get(source_key, {})
        target_culture = CULTURAL_PATTERNS.get(target_key, {})
        
        # Check for specific cultural references
        gaps = []
        bridges = []
        
        for ref, meaning in source_culture.get("common_refs", {}).items():
            if ref in text:
                gaps.append({"reference": ref, "meaning": meaning})
        
        # Use LLM for complex cultural bridging
        if self.api_key and gaps:
            bridge_result = self._llm_bridge(text, source_lang, target_lang, gaps, context)
            if bridge_result:
                bridges = bridge_result.get("bridges", [])
        
        return {
            "gaps": gaps,
            "bridges": bridges,
            "source_style": source_culture.get("humor_style", []),
            "target_preferences": target_culture.get("translation_preferences", {}),
        }
    
    def _llm_bridge(self, text: str, source_lang: str, target_lang: str, gaps: list, context: dict) -> dict:
        """LLM-based cultural bridging."""
        try:
            gaps_text = "\n".join(f"- {g['reference']}: {g['meaning']}" for g in gaps)
            prompt = f"""Bridge these cultural gaps for {source_lang}→{target_lang} dubbing:

TEXT: "{text}"
CULTURAL GAPS:
{gaps_text}

How should we adapt this for a {target_lang} audience?
Return JSON: {{"bridges": [{{"gap": "...", "solution": "...", "adapted_text": "..."}}], "keep_literal": true/false}}"""
            
            result = self._call_llm(prompt, 0.3)
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        return {}
    
    def predict_emotion_cause(self, segments: list[dict], target_index: int) -> dict:
        """
        Predict what caused the emotion at target_index by looking at BEFORE.
        Humans understand current emotion through past context.
        """
        if target_index < 1:
            return {"cause": "opening", "context": "first line"}
        
        before = segments[max(0, target_index - 3):target_index]
        current = segments[target_index]
        
        # Analyze the emotional trajectory
        emotions_before = [s.get("emotion", "neutral") for s in before]
        current_emotion = current.get("emotion", "neutral")
        
        # What caused the shift?
        cause = "continuation"
        if emotions_before and emotions_before[-1] != current_emotion:
            cause = f"shift_from_{emotions_before[-1]}"
        
        return {
            "cause": cause,
            "emotion_trajectory": emotions_before + [current_emotion],
            "is_escalation": self._is_escalating(emotions_before, current_emotion),
            "context_lines": [s.get("text", "") for s in before],
        }
    
    def _is_escalating(self, before: list, current: str) -> bool:
        """Check if emotions are escalating."""
        energy_map = {"calm": 1, "neutral": 2, "happy": 3, "sad": 3, "serious": 4, "angry": 5, "excited": 5, "fearful": 4}
        if not before:
            return False
        prev_energy = energy_map.get(before[-1], 2)
        curr_energy = energy_map.get(current, 2)
        return curr_energy > prev_energy
    
    def _call_llm(self, prompt: str, temperature: float = 0.3) -> str:
        headers = {"Authorization": f"Bearer {self.api_key}", "Content-Type": "application/json"}
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are an expert in cultural psychology and causal reasoning. Analyze why people say and feel things. Return JSON."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        }
        resp = requests.post(f"{self.api_base}/chat/completions", headers=headers, json=payload, timeout=30)
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
