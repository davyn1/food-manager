from fastapi import FastAPI


def create_app() -> FastAPI:
    app = FastAPI(title="Food Manager")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    return app


app = create_app()
