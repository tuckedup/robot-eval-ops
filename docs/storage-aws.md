# Using a user-owned S3 bucket (optional)

RobotEvalOps never creates buckets, edits bucket policy, or touches IAM. S3 is used only when you pass
`--store s3 --bucket <name>` explicitly; the default store is local. Credentials come only from boto3's
normal chain (environment variables, `~/.aws` shared config/SSO, instance/role); the tool accepts no keys.
The `s3` extra provides boto3 (`uv sync --extra s3`).

Minimum IAM actions on your bucket/prefix: `s3:PutObject`, `s3:GetObject`, `s3:ListBucket`
(`HeadObject` needs `GetObject`). Prefer a dedicated prefix such as `robotevalops/`.

## Tool commands

```
robotevalops data package runs/<session>                      # what would be sent / what is blocked
robotevalops data upload  runs/<session> --store s3 --bucket MY-BUCKET --prefix robotevalops
robotevalops data verify  runs/<session> --store s3 --bucket MY-BUCKET --prefix robotevalops
robotevalops data download <session_id> out/<session> --store s3 --bucket MY-BUCKET --prefix robotevalops
```

Objects are stored at `s3://MY-BUCKET/robotevalops/runs/<session_id>/<relpath>` with user metadata
`sha256`. `verify` downloads each object and recomputes SHA-256; the S3 ETag (an MD5 or multipart digest) is
never used as a content hash. An existing key with different bytes is refused (`ArtifactOverwriteError`).
Head-then-put is not an atomic conditional write: use one uploader per session.

## AWS CLI examples (you run these; the tool does not)

```
aws s3 ls s3://MY-BUCKET/robotevalops/runs/<session_id>/ --recursive
aws s3 sync runs/<session_id>/ s3://MY-BUCKET/robotevalops/runs/<session_id>/ --dryrun
aws s3 cp runs/<session_id>/manifest.json s3://MY-BUCKET/robotevalops/runs/<session_id>/manifest.json --dryrun
aws s3api head-object --bucket MY-BUCKET --key robotevalops/runs/<session_id>/manifest.json
```

`head-object` shows `Metadata.sha256` (the content hash the tool recorded) and an `ETag` that will differ.
Remove `--dryrun` yourself only after reviewing the output; note `aws s3 sync` does not honour the tool's
credential/symlink exclusions, so prefer `robotevalops data upload`.

## Testing

`pytest -m "not s3_real"` (CI) uses moto (mocked S3, which does not verify real AWS behaviour such as IAM,
KMS or multipart ETags). The opt-in real test runs only with `ROBOTEVALOPS_S3_BUCKET` set:
`pytest -m s3_real tests/data/test_storage_s3.py`.
