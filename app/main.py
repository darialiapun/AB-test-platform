import os

from fastapi import FastAPI, HTTPException

from app import storage
from app.bucketing import assign_variant
from app.schemas import (
    EventIn,
    EventOut,
    ExperimentCreate,
    ExperimentOut,
    ResultsOut,
    VariantOut,
)


def create_app(db_path: str) -> FastAPI:
    app = FastAPI(title="A/B Test Platform")
    app.state.db_path = db_path
    storage.init_db(db_path)

    @app.post("/experiments", response_model=ExperimentOut, status_code=201)
    def create_experiment(payload: ExperimentCreate) -> ExperimentOut:
        total_weight = sum(v.weight for v in payload.variants)
        if total_weight != 100:
            raise HTTPException(status_code=400, detail="Sum of variant weights must equal 100")
        variants = [v.model_dump() for v in payload.variants]
        experiment = storage.create_experiment(app.state.db_path, payload.name, variants)
        return experiment

    @app.get("/experiments/{experiment_id}/variant", response_model=VariantOut)
    def get_variant(experiment_id: str, user_id: str) -> VariantOut:
        experiment = storage.get_experiment(app.state.db_path, experiment_id)
        if experiment is None:
            raise HTTPException(status_code=404, detail="Experiment not found")

        existing = storage.get_assignment(app.state.db_path, experiment_id, user_id)
        if existing is not None:
            return VariantOut(experiment_id=experiment_id, user_id=user_id, variant=existing)

        variant = assign_variant(experiment["variants"], user_id, experiment_id)
        storage.create_assignment(app.state.db_path, experiment_id, user_id, variant)
        return VariantOut(experiment_id=experiment_id, user_id=user_id, variant=variant)

    @app.post("/events", response_model=EventOut, status_code=201)
    def record_event(payload: EventIn) -> EventOut:
        experiment = storage.get_experiment(app.state.db_path, payload.experiment_id)
        if experiment is None:
            raise HTTPException(status_code=404, detail="Experiment not found")
        storage.create_event(app.state.db_path, payload.experiment_id, payload.user_id, payload.event_type)
        return EventOut(status="recorded")

    @app.get("/experiments/{experiment_id}/results", response_model=ResultsOut)
    def get_results(experiment_id: str) -> ResultsOut:
        experiment = storage.get_experiment(app.state.db_path, experiment_id)
        if experiment is None:
            raise HTTPException(status_code=404, detail="Experiment not found")
        variant_names = [v["name"] for v in experiment["variants"]]
        results = storage.get_results(app.state.db_path, experiment_id, variant_names)
        return ResultsOut(variants=results)

    return app


DEFAULT_DB_PATH = os.environ.get("AB_TEST_DB_PATH", "ab_test.db")
app = create_app(DEFAULT_DB_PATH)
