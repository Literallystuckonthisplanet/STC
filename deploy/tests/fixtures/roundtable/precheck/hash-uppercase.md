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
  sha256: 67B2D5A5FAC29F2A0D981FE74B2D86276DCAFB1E7838C10813494E37D5922F55
active_capabilities:
- read
forbidden_capabilities:
- write
---

# Артефакт

Текст документа не разбирается; здесь могут стоять ref:fake и слова write.
