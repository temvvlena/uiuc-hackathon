from herdx_model import MODEL_PATH, train_and_save


if __name__ == "__main__":
    artifact = train_and_save()
    print(
        f"Saved {artifact['target']} model trained on "
        f"{artifact['training_rows']} records to {MODEL_PATH}"
    )
