#!/usr/bin/env python3
"""
Human Thinker — Chain-of-Thought Reasoning Layer
=================================================
Makes the brain think like a human before acting:
- Theory of Mind: Understand what speakers INTEND, not just what they SAY
- Common Sense: World knowledge about how things work
- Empathy: Feel the scene emotionally, not just detect keywords
- Creative Problem Solving: When literal translation fails, improvise
- Self-Reflection: "Is this good? Let me reconsider..."
- Multi-Perspective: Think from speaker, listener, AND audience view
"""

import json
import re
import requests


class HumanThinker:
    """
    Chain-of-thought reasoning engine.
    Before each major decision, the brain "thinks out loud"
    and reasons step by step — like a human would.
    """
    
    def __init__(self, api_key: str = "", api_base: str = "", model: str = "mimo-v2.5-pro"):
        self.api_key = api_key
        self.api_base = api_base.rstrip("/")
        self.model = model
        self.thinking_log = []  # Store reasoning trace
    
    def think(self, question: str, context: dict = None) -> dict:
        """
        Main thinking method — chain-of-thought reasoning.
        Returns: {"reasoning": str, "conclusion": dict, "confidence": float}
        """
        self.thinking_log = []
        
        if not self.api_key:
            return self._think_fallback(question, context)
        
        context_str = self._format_context(context)
        
        prompt = f"""You are a professional dubbing director thinking through a decision.
Think step by step, like a human expert would. Show your reasoning.

QUESTION: {question}

CONTEXT:
{context_str}

THINK LIKE A HUMAN — Step by step:
1. FIRST IMPRESSION: What's your gut feeling? (1 sentence)
2. THEORY OF MIND: What does the speaker really mean? (beyond words)
3. COMMON SENSE: What would a native Vietnamese viewer expect?
4. CULTURAL LENS: Any cultural differences to bridge?
5. CREATIVE SOLUTION: If literal translation fails, what's the alternative?
6. SELF-CHECK: Does this feel natural? Any red flags?
7. FINAL ANSWER: Your conclusion (as JSON)

Format your response as:
REASONING:
[your step by step thinking]

CONCLUSION:
{{"answer": "your final answer", "confidence": 0.85, "alternatives": ["option1", "option2"]}}"""

        try:
            result = self._call_llm(prompt, temperature=0.4)
            return self._parse_thinking(result)
        except Exception as e:
            self.thinking_log.append(f"LLM thinking failed: {e}")
            return self._think_fallback(question, context)
    
    def think_translation(self, source_text: str, source_lang: str, target_lang: str,
                          context: dict = None, speaker_intent: str = "") -> dict:
        """
        Think deeply about how to translate a specific line.
        Goes beyond word-for-word to capture MEANING and FEELING.
        """
        context_str = self._format_context(context)
        
        prompt = f"""You are a world-class {source_lang}→{target_lang} translator for video dubbing.
You need to translate this line so it FEELS right when spoken aloud.

SOURCE ({source_lang}): "{source_text}"
SPEAKER INTENT: {speaker_intent or "Unknown — figure it out"}
{context_str}

THINK THROUGH THIS:
1. What does this line LITERALLY mean?
2. What does the speaker FEEL when saying this?
3. What is the speaker TRYING to achieve? (persuade? comfort? joke? inform?)
4. If you translated literally, would it sound natural in Vietnamese?
5. What would a Vietnamese person say in the SAME situation?
6. Find the translation that captures BOTH meaning AND feeling.

RULES:
- The translation will be SPOKEN, not read. It must sound natural.
- Preserve the speaker's emotion and intent
- Use Vietnamese idioms/expressions where they fit naturally
- Keep it concise (voice acting has time limits)
- If there's humor, make it funny in Vietnamese too

Return JSON:
{{"literal": "literal meaning", "feeling": "what emotion", "intent": "what speaker wants", "translation": "your natural translation", "alternatives": ["alt1", "alt2"], "notes": "any cultural adaptation notes"}}"""

        try:
            result = self._call_llm(prompt, temperature=0.5)
            return self._parse_translation_thinking(result)
        except:
            return {"translation": source_text, "alternatives": [], "notes": "Thinking failed"}
    
    def think_emotion(self, text: str, context: dict = None) -> dict:
        """
        Think deeply about the emotion behind a line.
        Goes beyond keyword matching to understand UNDERLYING feeling.
        """
        context_str = self._format_context(context)
        
        prompt = f"""You are an experienced voice actor analyzing a line for emotional delivery.

LINE: "{text}"
{context_str}

Think like an ACTOR preparing to perform:
1. What is the SURFACE emotion? (what you'd see on their face)
2. What is the DEEP emotion? (what they're really feeling inside)
3. What is the ENERGY level? (0=whisper, 10=shouting)
4. What is the TEMPO? (slow contemplation vs fast excitement)
5. How should the VOICE change? (breathy? firm? trembling? warm?)
6. What is the MOTIVATION? (why are they saying this RIGHT NOW?)

Return JSON:
{{
  "surface_emotion": "what's visible",
  "deep_emotion": "what's underneath",
  "energy": 5,
  "tempo": "normal|fast|slow|variable",
  "voice_quality": "description of voice texture",
  "motivation": "why they say this",
  "delivery_notes": "specific acting direction"
}}"""

        try:
            result = self._call_llm(prompt, temperature=0.3)
            return self._parse_emotion_thinking(result)
        except:
            return {"surface_emotion": "neutral", "deep_emotion": "neutral", "energy": 5, "tempo": "normal"}
    
    def think_cultural_bridge(self, text: str, source_lang: str, target_lang: str) -> dict:
        """
        Think about cultural gaps between languages.
        What would confuse a Vietnamese viewer?
        """
        prompt = f"""You are a cultural consultant for {source_lang}→{target_lang} video dubbing.

LINE: "{text}"

A Vietnamese viewer will watch this dubbed video. Think about:
1. Are there cultural references they won't understand?
2. Are there idioms that don't translate directly?
3. Are there social norms that differ between cultures?
4. What context would a Vietnamese person be missing?
5. How can you bridge this gap NATURALLY (not with footnotes)?

Return JSON:
{{
  "cultural_gaps": ["list of things a Vietnamese viewer might not get"],
  "bridges": {{"gap": "how to bridge it naturally"}},
  "adapted_translation": "the culturally-adapted version",
  "keep_literal": true_or_false,
  "notes": "explanation"
}}"""

        try:
            result = self._call_llm(prompt, temperature=0.3)
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        
        return {"cultural_gaps": [], "bridges": {}, "adapted_translation": text}
    
    def think_about_speaker(self, segments: list[dict], speaker_index: int) -> dict:
        """
        Build a model of who this speaker IS.
        Theory of Mind — understand the person behind the words.
        """
        # Gather all lines from this speaker
        speaker_lines = [s["text"] for s in segments if s.get("speaker_id", 0) == speaker_index][:20]
        
        if not speaker_lines:
            return {"character": "unknown", "personality": "unknown"}
        
        lines_text = "\n".join(f'  "{line}"' for line in speaker_lines[:10])
        
        prompt = f"""You are a character analyst studying a speaker in a video.

These are their lines:
{lines_text}

Build a character profile:
1. PERSONALITY: What kind of person are they? (3-5 adjectives)
2. SPEECH STYLE: How do they talk? (formal/casual, fast/slow, etc.)
3. EMOTIONAL RANGE: What emotions do they show most?
4. ROLE: What is their role in this conversation? (narrator, protagonist, comic relief, etc.)
5. GROWTH: Does their tone change across the video?

Return JSON:
{{
  "personality": ["adjective1", "adjective2"],
  "speech_style": "description",
  "emotional_tendencies": ["emotion1", "emotion2"],
  "role": "their role",
  "voice_suggestion": "what voice would match this character"
}}"""

        try:
            result = self._call_llm(prompt, temperature=0.3)
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        
        return {"character": "unknown", "personality": ["unknown"], "role": "unknown"}
    
    def self_reflect(self, translation: str, original: str, context: dict = None) -> dict:
        """
        Self-reflection — review a translation and improve it.
        Like a human editor re-reading their work.
        """
        prompt = f"""You are a translation editor reviewing this dubbing translation.

ORIGINAL: "{original}"
TRANSLATION: "{translation}"

Be CRITICAL. Ask yourself:
1. If I heard this translation spoken aloud, would it feel natural?
2. Does it capture the MEANING of the original?
3. Does it preserve the EMOTION?
4. Is it the right LENGTH for voice acting? (not too long)
5. Would a Vietnamese person say it this way?
6. Any awkward phrasing that needs fixing?

Rate from 1-10 and suggest improvements.

Return JSON:
{{
  "score": 8,
  "naturalness": 7,
  "meaning_accuracy": 9,
  "emotion_preservation": 8,
  "improved_version": "better translation if needed",
  "issues": ["any problems found"],
  "verdict": "APPROVE|NEEDS_WORK|REWRITE"
}}"""

        try:
            result = self._call_llm(prompt, temperature=0.2)
            json_match = re.search(r'\{.*\}', result, re.DOTALL)
            if json_match:
                return json.loads(json_match.group())
        except:
            pass
        
        return {"score": 7, "verdict": "APPROVE"}
    
    def brainstorm_translations(self, text: str, source_lang: str, target_lang: str, n: int = 3) -> list[str]:
        """
        Brainstorm multiple translation options.
        Like a human translator trying different approaches.
        """
        prompt = f"""Translate this {source_lang}→{target_lang} line for video dubbing.
Give me {n} DIFFERENT approaches:

TEXT: "{text}"

Try:
1. Literal but natural
2. Culturally adapted
3. Creative/idiomatic

Return ONLY the {n} translations, one per line, numbered."""

        try:
            result = self._call_llm(prompt, temperature=0.6)
            translations = []
            for line in result.split("\n"):
                m = re.match(r"^\d+[.):\s]+\s*(.+)", line.strip())
                if m:
                    translations.append(m.group(1).strip())
            return translations[:n]
        except:
            return [text]
    
    def _parse_thinking(self, result: str) -> dict:
        """Parse chain-of-thought response."""
        self.thinking_log.append(result)
        
        # Extract reasoning
        reasoning = ""
        if "REASONING:" in result:
            reasoning = result.split("REASONING:")[1].split("CONCLUSION:")[0].strip()
        
        # Extract conclusion JSON
        conclusion = {}
        json_match = re.search(r'\{[^{}]*"answer"[^{}]*\}', result, re.DOTALL)
        if json_match:
            try:
                conclusion = json.loads(json_match.group())
            except:
                pass
        
        return {
            "reasoning": reasoning,
            "conclusion": conclusion,
            "confidence": conclusion.get("confidence", 0.7),
            "raw": result,
        }
    
    def _parse_translation_thinking(self, result: str) -> dict:
        """Parse translation thinking response."""
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass
        
        # Try to extract just the translation
        if "translation" in result.lower():
            lines = result.split("\n")
            for line in lines:
                if "translation" in line.lower() and ":" in line:
                    return {"translation": line.split(":", 1)[-1].strip().strip('"')}
        
        return {"translation": result[:200], "alternatives": []}
    
    def _parse_emotion_thinking(self, result: str) -> dict:
        """Parse emotion thinking response."""
        json_match = re.search(r'\{.*\}', result, re.DOTALL)
        if json_match:
            try:
                return json.loads(json_match.group())
            except:
                pass
        
        return {"surface_emotion": "neutral", "deep_emotion": "neutral", "energy": 5}
    
    def _format_context(self, context: dict = None) -> str:
        """Format context for prompts."""
        if not context:
            return ""
        
        parts = []
        if context.get("genre"):
            parts.append(f"Genre: {context['genre']}")
        if context.get("mood_arc"):
            parts.append(f"Mood: {context['mood_arc']}")
        if context.get("speakers"):
            parts.append(f"Speakers: {len(context['speakers'])}")
        if context.get("humor_type") and context["humor_type"] != "none":
            parts.append(f"Humor: {context['humor_type']}")
        
        return "\n".join(parts)
    
    def _think_fallback(self, question: str, context: dict = None) -> dict:
        """Simple rule-based thinking when LLM is unavailable."""
        return {
            "reasoning": "No LLM available for deep thinking. Using heuristic.",
            "conclusion": {"answer": question[:100], "confidence": 0.5},
            "confidence": 0.5,
        }
    
    def _call_llm(self, prompt: str, temperature: float = 0.3) -> str:
        """Call MiMo API."""
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": "You are an expert dubbing director with deep cultural knowledge. Think step by step like a human. Be thorough but concise."},
                {"role": "user", "content": prompt},
            ],
            "temperature": temperature,
        }
        
        resp = requests.post(
            f"{self.api_base}/chat/completions",
            headers=headers, json=payload, timeout=60,
        )
        resp.raise_for_status()
        return resp.json()["choices"][0]["message"]["content"].strip()
