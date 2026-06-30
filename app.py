"""Canonical FastAPI entrypoint for CertiFlow."""

from api import app


def main() -> None:
    import uvicorn

    uvicorn.run("app:app", host="0.0.0.0", port=8000, reload=False)


if __name__ == "__main__":
    main()
