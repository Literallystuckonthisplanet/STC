---
revision: r1
sections:
- id: s1
  anchors:
  - ref:a
references:
- ref:a
lists:
- name: files
  declared_count: 2
  items:
  - a
  - b
evidence:
- path: docs/removed.md
  sha256: f0c693f2bc9e0d7b0aac0f13d9dfaafc443cdf13b7e21b6bc13808cb327160dc
active_capabilities:
- read
forbidden_capabilities:
- write
---

# Артефакт

Текст документа не разбирается; здесь могут стоять ref:fake и слова write.
