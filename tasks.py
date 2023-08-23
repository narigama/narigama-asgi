import invoke


@invoke.task()
def dev_start(ctx: invoke.Context):
    ctx.run("docker compose up -d --wait")


@invoke.task()
def dev_stop(ctx: invoke.Context):
    ctx.run("docker compose down -v")


@invoke.task(pre=[dev_start])
def test_run(ctx: invoke.Context):
    ctx.run("pytest --cov=narigama_asgi --cov-report=xml:coverage.xml")
