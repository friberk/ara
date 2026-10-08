from minio.error import S3Error

from app.core.config import Settings
from app.core.resources import Resources


def initialize_bucket(storage, bucket: str) -> None:
    if not storage.bucket_exists(bucket):
        try:
            storage.make_bucket(bucket)
        except S3Error as error:
            if error.code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise
    # Idempotently remove anonymous policies, including ones left by manual setup.
    storage.delete_bucket_policy(bucket)


async def main() -> None:
    resources = Resources(Settings())
    try:
        await resources.storage_call(
            initialize_bucket, resources.storage, resources.settings.minio_bucket
        )
        print("Private storage bucket initialized")
    finally:
        await resources.close()


if __name__ == "__main__":
    import asyncio

    asyncio.run(main())
