# Quick Reference - S3 Bucket Encryption

## Configuration Options

### Option 1: Default (S3-Managed)
```yaml
KMSKeyAlias: ""
ManageBucketEncryption: "yes"
DataBucketsKmsKeysArns: ""
```

### Option 2: KMS with Alias
```yaml
KMSKeyAlias: "cid-data-collection-key"
ManageBucketEncryption: "yes"
DataBucketsKmsKeysArns: ""
```

### Option 3: External Management ⚠️
```yaml
KMSKeyAlias: ""
ManageBucketEncryption: "no"
DataBucketsKmsKeysArns: "arn:aws:kms:..."
```
⚠️ [Read warnings first](ENCRYPTION_WARNING.md)

## Common Commands

### Deploy with Default
```bash
aws cloudformation create-stack \
  --stack-name cid-data-collection \
  --template-body file://deploy-data-collection.yaml \
  --capabilities CAPABILITY_NAMED_IAM
```

### Deploy with KMS Alias
```bash
aws cloudformation create-stack \
  --stack-name cid-data-collection \
  --template-body file://deploy-data-collection.yaml \
  --parameters ParameterKey=KMSKeyAlias,ParameterValue=my-key \
  --capabilities CAPABILITY_NAMED_IAM
```

### Create KMS Key with Alias
```bash
KEY_ID=$(aws kms create-key --region us-east-1 \
  --query 'KeyMetadata.KeyId' --output text)
aws kms create-alias \
  --alias-name alias/cid-data-collection-key \
  --target-key-id $KEY_ID \
  --region us-east-1
```

## Common Questions

**Q: Which option should I use?**
A: Default for most users, KMS Alias for compliance, External only with AWS Config automation

**Q: Is this backward compatible?**
A: Yes! Existing deployments work without changes.

**Q: What's the cost?**
A: Default: $0, KMS: ~$3-5/month

## Documentation

- 📖 [Complete Guide](ENCRYPTION.md)
- ⚠️ [Warning Guide](ENCRYPTION_WARNING.md)
- 📚 [Main README](../README.md)
