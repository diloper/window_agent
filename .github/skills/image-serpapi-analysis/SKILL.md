---
name: image-serpapi-analysis
description: "Standardized workflow for analyzing an image with SerpApi image search results."
argument-hint: "Provide an image path, for example: analyze image recordings/A.png"
user-invocable: true
---

# Image SerpApi Analysis Skill

## Purpose
Standardize the flow for analyzing image search results from a local image path with minimal manual parameter entry.

## Trigger Patterns
- "分析 圖片 結果"
- "serpapi 分析 圖片"
- "analyze image with serpapi"
- "analyze image results"

## Default Procedure
1. Parse image path from user input.
2. If only a filename is provided, check recordings/<filename> first.
3. Run google-search-results.py with the image path.
4. Return top repetition result from visual matches.

## Standard Command
C:/Users/User/miniconda3/python.exe google-search-results.py <image_path>

## Notes
- image_path is required; no default path is used.
- If API key is missing, set SERPAPI_API_KEY in environment.
- The uploaded image is automatically deleted from Postimages after the search completes.
