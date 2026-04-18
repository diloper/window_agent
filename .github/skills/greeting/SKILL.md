---
name: greeting
description: "Use when user says hello, hi, 哈囉, or asks for a greeting. Trigger on greeting intent and respond with a brief, friendly opener in the user's language."
---

# Greeting Skill

## Purpose
Respond cleanly when the user starts with a greeting.

## Trigger Phrases
- hello
- hi
- 哈囉
- greeting intent (for example: "say hello", "greet me")

## Response Rules
1. Reply with a short, friendly greeting in the same language as the user message.
2. Add one concise follow-up question to move the conversation forward.
3. Keep the response brief (1 to 2 sentences) unless the user asks for more detail.
4. Do not override task-specific instructions if the user asks for coding work.

## Examples
- User: "hello"
  Assistant: "Hello! What would you like to work on today?"
- User: "hi"
  Assistant: "Hi! How can I help with your project?"
- User: "哈囉"
  Assistant: "哈囉！今天想先處理哪一部分？"
