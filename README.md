# A/B-test platform

An A/B testing service: deterministic assignment of users to experiment variants, event collection, and statistical significance testing of the results.

## Overview

An experiment owner (product manager / analyst / project owner) wants to test a hypothesis ("variant B performs better than variant A"). The service covers the full cycle: create an experiment → deterministically assign a variant to each user → record events → calculate conversion and the statistical significance of the difference between variants, with explicit warnings wherever there is not enough data for a reliable conclusion.

Built during the Agentic Engineering course (MIPT, Fall 2026) using spec-driven development with an AI coding agent: product brief → formal requirements with acceptance criteria → implementation → automated tests.

## Features

* **Deterministic bucketing:** a user's variant is computed by hashing (`sha256` of `user_id + experiment_id`), with no stored state — the same user always lands in the same variant.
* **Automatic choice of statistical test:** z-test or Fisher's exact test, depending on the amount of data in the group (threshold: `np < 5` or `n(1-p) < 5` → Fisher), so the normal approximation is not trusted on small samples.
* **Honest null:** when there is not enough data for a conclusion (zero conversion in control, an experiment that is too young, a skewed sample ratio), the service returns `status = "insufficient_data"` or `srm = null` together with the reason.
* **Multiple comparisons correction:** with several treatment variants — Benjamini–Hochberg (FDR), with a comparison "family" that correctly excludes `insufficient_data` (see REQ-10 in [spec.md](spec.md)).
* **Sample ratio mismatch detector (optional):** `?check_srm=true` — a chi-square test of whether the actual distribution of users across variants matches the configured weights; strict threshold `p < 0.01`.
* **Test duration estimate:** if there is not yet enough power, `/results` calculates `estimated_days_needed` based on each variant's own enrolment rate.

## API

| Method | Path | What it does |
|---|---|---|
| `POST` | `/experiments` | Create an experiment (validation: weights sum to 100, at least 2 variants) |
| `GET` | `/experiments/{id}/variant?user_id=` | Get the variant for a user (deterministic) |
| `POST` | `/events` | Record an event (e.g. `conversion`) |
| `GET` | `/experiments/{id}/results?check_srm=` | Conversion per variant + statistical significance, optional SRM check |

The full contract with request/response examples is in [spec.md](spec.md#3-контракт-api) (in Russian).

## Quick start

```bash
make install   # python3 -m pip install -r requirements.txt
make test      # full test suite (excluding the perf test)
make run       # run locally (uvicorn, --reload)
```

Swagger documentation is available at `/docs` after `make run`.

## How it is verified

29 tests: 28 in `make test`, plus a separate load test (`make test-perf`), which is excluded from the regular run so as not to make it flaky. The statistical formulas are checked against reference libraries — `scipy.stats.proportions_ztest`, `scipy.stats.fisher_exact`, `statsmodels.stats.multitest.multipletests` — to within 0.001.

Every behaviour is formalised as an EARS requirement (REQ-1…14; Ubiquitous / Event-driven / Unwanted behaviour / Optional feature templates) with Gherkin acceptance criteria in [spec.md §3.2](spec.md), and decisions with a non-trivial rationale have separate ADRs in [docs/adr/](docs/adr/) (for example, why the confidence interval is always computed with the Wald method, even when Fisher's test is chosen for the p-value).

## Tech stack

FastAPI · SQLite · scipy · statsmodels · pytest

## Documentation (in Russian)

- Specification: [spec.md](spec.md) — API contract, data model, formal requirements, what the tests prove
- Glossary: [GLOSSARY.md](GLOSSARY.md) — project terms (e.g. what exactly "control" means in this service)
- ADRs: [docs/adr/](docs/adr/) — rationale for non-trivial statistical decisions
- Project card: [project-card.md](project-card.md)

## Status

The backend works: experiment creation, bucketing, events, conversion, statistical significance (z-test/Fisher + Wald CI + BH correction), optional SRM check. No frontend yet (Swagger only) and no deployment — runs locally via `make run`.




# A/B-test platform

Сервис A/B-тестирования: детерминированное разделение пользователей по экспериментам, сбор событий и проверка статистической значимости результата.

## Обзор

Владелец эксперимента (продакт/аналитик/владелец проекта) хочет проверить гипотезу («вариант B работает лучше варианта A»). Сервис решает полный цикл: создание эксперимента → детерминированная выдача варианта пользователю → запись событий → расчёт конверсии и статистической значимости разницы между вариантами, с явными предупреждениями там, где данных недостаточно для надёжного вывода.

## Особенности

* **Детерминированный бакетинг:** вариант для пользователя вычисляется хэшем (`sha256` от `user_id + experiment_id`), без хранения состояния — один и тот же пользователь всегда попадает в один и тот же вариант.
* **Автоматический выбор статтеста:** z-test или точный тест Фишера — в зависимости от объёма данных в группе (порог: `np < 5` или `n(1-p) < 5` → Фишер), чтобы не доверять нормальному приближению на малых выборках.
* **Honest null:** если данных недостаточно для вывода (нулевая конверсия контроля, слишком юный эксперимент, скошенный sample ratio) — сервис возвращает `status = "insufficient_data"` или `srm = null` с объяснением причины.
* **Поправка на множественные сравнения:** при нескольких тестовых вариантах — Бенджамини-Хохберга (FDR), с «семьёй» сравнений, корректно исключающей `insufficient_data` (см. REQ-10 в [spec.md](spec.md)).
* **Детектор sample ratio mismatch (опционально):** `?check_srm=true` — хи-квадрат тест на соответствие фактического распределения пользователей по вариантам заданным весам; строгий порог `p < 0.01`.
* **Оценка времени теста:** если мощности пока не хватает, `/results` считает `estimated_days_needed` по собственному темпу набора каждого варианта.

## API

| Метод | Путь | Что делает |
|---|---|---|
| `POST` | `/experiments` | Создать эксперимент (валидация: сумма весов = 100, минимум 2 варианта) |
| `GET` | `/experiments/{id}/variant?user_id=` | Получить вариант для пользователя (детерминированно) |
| `POST` | `/events` | Записать событие (например, `conversion`) |
| `GET` | `/experiments/{id}/results?check_srm=` | Конверсия по вариантам + статзначимость, опционально SRM-проверка |

Полный контракт с примерами запросов/ответов — в [spec.md](spec.md#3-контракт-api).

## Быстрый старт

```bash
make install   # python3 -m pip install -r requirements.txt
make test      # полный набор тестов (без perf-теста)
make run       # запустить локально (uvicorn, --reload)
```

Swagger-документация после `make run` — на `/docs`.

## Как это проверяется

29 тестов: 28 в `make test`, и отдельный нагрузочный тест (`make test-perf`, не входит в обычный прогон, чтобы не делать его нестабильным. Статистические формулы сверяются с эталонными библиотеками — `scipy.stats.proportions_ztest`, `scipy.stats.fisher_exact`, `statsmodels.stats.multitest.multipletests` — с точностью до 0.001.

Каждое поведение формализовано как EARS-требование (REQ-1…14, шаблоны Ubiquitous / Event-driven / Unwanted behavior / Optional feature) с Гёркин-критериями приёмки в [spec.md §3.2](spec.md), и для решений с нетривиальным обоснованием — отдельные ADR в [docs/adr/](docs/adr/) (например, почему доверительный интервал всегда считается по Wald, даже когда для p-value выбран Фишер).

## Технологии

FastAPI · SQLite · scipy · statsmodels · pytest

## Документация

- Спецификация: [spec.md](spec.md) — контракт API, модель данных, формальные требования, что доказывается тестами
- Глоссарий: [GLOSSARY.md](GLOSSARY.md) — термины проекта (например, что именно значит «контроль» в этом сервисе)
- ADR: [docs/adr/](docs/adr/) — обоснование нетривиальных статистических решений
- Карточка проекта: [project-card.md](project-card.md)

## Статус

Бэкенд рабочий: создание эксперимента, бакетинг, события, конверсия, статзначимость (z-test/Фишер + Wald CI + BH-поправка), опциональная SRM-проверка. Пока без фронтенда (только Swagger) и без деплоя — локальный запуск через `make run`.
