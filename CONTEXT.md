# Контекст сессий

## 2026-10-30: REQ-14 — отклонение эксперимента с < 2 вариантами в POST /experiments

**Что сделано:** `POST /experiments` теперь отклоняет запрос с 400, если передано меньше двух вариантов (0 или 1). Раньше это проверялось только в `GET /experiments/{id}/results` — теперь проверка перенесена на создание, а проверка в `/results` удалена как недостижимая (создать такой эксперимент стало невозможно).

**Тесты:**
- `tests/test_experiments.py::test_create_experiment_rejects_fewer_than_two_variants` — новый тест, red→green подтверждён (упал с `201 == 400`, стал зелёным после добавления проверки в `app/main.py`).
- `tests/test_significance.py::test_single_variant_experiment_rejected_at_creation` — переписан из `test_single_variant_experiment_returns_error`, который раньше проверял отказ на `/results`; теперь проверяет отказ на `POST /experiments`.
- Полный `make test`: 28 passed.

**Решение, принятое с пользователем:** старый тест на одиночный вариант был переписан (не удалён) под новое поведение, а дублирующая проверка в `/results` удалена, а не оставлена как defensive dead code — пользователь выбрал вариант "переписать тест на POST, проверку в /results удалить".

**Открытые вопросы:** нет.
