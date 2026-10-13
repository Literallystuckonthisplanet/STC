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
- path: docs/plan.md
  sha256: 67b2d5a5fac29f2a0d981fe74b2d86276dcafb1e7838c10813494e37d5922f55
active_capabilities:
- read
- write-docs
forbidden_capabilities:
- write
- delete
---

# Артефакт

Текст документа не разбирается; здесь могут стоять ref:fake и слова write.
