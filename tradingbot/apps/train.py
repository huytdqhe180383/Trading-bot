"""Application entrypoint for PPO/SAC training."""


def main() -> None:
    from train import main as train_main

    train_main()
