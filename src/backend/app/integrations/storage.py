def read_object(storage, bucket: str, key: str, max_bytes: int) -> bytes:
    response = storage.get_object(bucket, key)
    try:
        data = response.read(max_bytes + 1)
        if len(data) > max_bytes:
            raise ValueError("Object exceeds size limit")
        return data
    finally:
        response.close()
        response.release_conn()
