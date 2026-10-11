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
  sha256: 49ea046be3d96b56992789d927796837010823a94c7213f155d8f96859a2879a
active_capabilities:
- read
forbidden_capabilities:
- write
---

# Артефакт

Текст документа не разбирается; здесь могут стоять ref:fake и слова write.
