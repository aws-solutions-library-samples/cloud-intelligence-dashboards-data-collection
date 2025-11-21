# S3 Bucket Encryption Configuration Guide

## Quick Start - Choose Your Option

```
┌─────────────────────────────────────────────────────────────────┐
│                  Which encryption option do I need?             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Option 1: Default (Recommended for Most Users)                 │
│ Simple, secure, managed by CloudFormation                       │
├─────────────────────────────────────────────────────────────────┤
│ KMSKeyAlias: ""                                                 │
│ ManageBucketEncryption: "yes"                                   │
│ DataBucketsKmsKeysArns: ""                                      │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Option 2: Customer-Managed KMS Keys                            │
│ Recommended for compliance requirements                         │
├─────────────────────────────────────────────────────────────────┤
│ KMSKeyAlias: "my-key-alias"                                     │
│ ManageBucketEncryption: "yes"                                   │
│ DataBucketsKmsKeysArns: ""                                      │
│                                                                 │
│ Prerequisites:                                                  │
│ • Create KMS keys in each region                               │
│ • Create same alias in each region                             │
└─────────────────────────────────────────────────────────────────┘

┌─────────────────────────────────────────────────────────────────┐
│ Option 3: External Management (ADVANCED USERS ONLY)             │
│ YOU manage encryption, NOT CloudFormation                       │
├─────────────────────────────────────────────────────────────────┤
│ KMSKeyAlias: ""                                                 │
│ ManageBucketEncryption: "no"                                    │
│ DataBucketsKmsKeysArns: "arn:aws:kms:..."                       │
│                                                                 │
│ READ ENCRYPTION_WARNING.md FIRST!                              │
│                                                                 │
│ Requirements:                                                   │
│ • AWS Config rules for encryption enforcement                  │
│ • Automation to apply encryption                               │
│ • Monitoring for unencrypted buckets                           │
│ • Documented processes                                         │
└─────────────────────────────────────────────────────────────────┘
```

## Parameter Reference

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| **KMSKeyAlias** | String | "" | KMS key alias name (same across regions). Example: `cid-data-collection-key` |
| **ManageBucketEncryption** | String | "yes" | Let CloudFormation manage encryption? **Recommended: yes** |
| **DataBucketsKmsKeysArns** | String | "" | Legacy: KMS key ARNs for IAM permissions only |

## Decision Tree

```
Start Here
    |
    v
Do you have AWS Config rules that manage encryption?
    |
    ├─ YES ──> Do you want CloudFormation to also manage it?
    |           |
    |           ├─ NO ──> Option 3: External Management
    |           |         (Read ENCRYPTION_WARNING.md)
    |           |
    |           └─ YES ──> Option 2: KMS with Alias
    |                      (CloudFormation manages, AWS Config validates)
    |
    └─ NO ──> Do you need customer-managed KMS keys?
              |
              ├─ YES ──> Option 2: KMS with Alias
              |
              └─ NO ──> Option 1: Default (S3-managed)
```

## Detailed Options

### Option 1: Default (S3-Managed Encryption)

**Configuration:**
```yaml
# No parameters needed - these are the defaults
KMSKeyAlias: ""
ManageBucketEncryption: "yes"
DataBucketsKmsKeysArns: ""
```

**What happens:**
- Buckets encrypted with AES256 (S3-managed keys)
- CloudFormation manages encryption
- No additional cost
- No setup required

**Best for:**
- Most deployments
- No special compliance requirements
- Simplest option

**Deploy:**
```bash
aws cloudformation create-stack \
  --stack-name cid-data-collection \
  --template-body file://deploy-data-collection.yaml \
  --capabilities CAPABILITY_NAMED_IAM
```

---

### Option 2: KMS with Alias

**Configuration:**
```yaml
KMSKeyAlias: "cid-data-collection-key"
ManageBucketEncryption: "yes"
DataBucketsKmsKeysArns: ""
```

**What happens:**
- Buckets encrypted with customer-managed KMS keys
- CloudFormation manages encryption
- IAM permissions configured automatically
- Works across all regions with same alias

**Best for:**
- Compliance requirements for customer-managed keys
- Multi-region deployments
- Need key rotation control
- Audit trail requirements

**Setup Steps:**

1. **Create KMS keys and aliases in each region:**
```bash
# Region 1 (us-east-1)
KEY_ID_1=$(aws kms create-key --region us-east-1 \
  --description "CID Data Collection Encryption Key" \
  --query 'KeyMetadata.KeyId' --output text)

aws kms create-alias \
  --alias-name alias/cid-data-collection-key \
  --target-key-id $KEY_ID_1 \
  --region us-east-1

# Region 2 (us-west-2)
KEY_ID_2=$(aws kms create-key --region us-west-2 \
  --description "CID Data Collection Encryption Key" \
  --query 'KeyMetadata.KeyId' --output text)

aws kms create-alias \
  --alias-name alias/cid-data-collection-key \
  --target-key-id $KEY_ID_2 \
  --region us-west-2

# Repeat for all regions in RegionsInScope parameter
```

2. **Deploy stack:**
```bash
aws cloudformation create-stack \
  --stack-name cid-data-collection \
  --template-body file://deploy-data-collection.yaml \
  --parameters ParameterKey=KMSKeyAlias,ParameterValue=cid-data-collection-key \
  --capabilities CAPABILITY_NAMED_IAM
```

**Cost:** ~$3-5/month (keys + API calls)

---

### Option 3: External Management

**CRITICAL: Read [ENCRYPTION_WARNING.md](ENCRYPTION_WARNING.md) before using this option!**

**Configuration:**
```yaml
KMSKeyAlias: ""
ManageBucketEncryption: "no"
DataBucketsKmsKeysArns: "arn:aws:kms:us-east-1:123456789012:key/abc-123,arn:aws:kms:us-west-2:123456789012:key/def-456"
```

**What happens:**
- CloudFormation does NOT configure encryption
- CloudFormation does NOT validate encryption
- Drift detection does NOT report encryption changes
- IAM permissions configured for KMS
- **YOU are responsible for encryption**

**Best for:**
- AWS Config manages encryption
- Centralized security team controls encryption
- Existing automation applies encryption
- Advanced users with documented processes

**Your Responsibilities:**
1. Ensuring buckets are encrypted immediately after stack creation
2. Maintaining encryption configuration across stack updates
3. Monitoring encryption status via AWS Config or other tools
4. Meeting compliance requirements for data encryption
5. Documenting your encryption management process

**Setup Steps:**

1. **Deploy stack with external management:**
```bash
aws cloudformation create-stack \
  --stack-name cid-data-collection \
  --template-body file://deploy-data-collection.yaml \
  --parameters \
    ParameterKey=ManageBucketEncryption,ParameterValue=no \
    ParameterKey=DataBucketsKmsKeysArns,ParameterValue="arn:aws:kms:us-east-1:123456789012:key/abc-123" \
  --capabilities CAPABILITY_NAMED_IAM
```

2. **Immediately apply encryption:**
```bash
# Get bucket name from stack outputs
BUCKET_NAME=$(aws cloudformation describe-stacks \
  --stack-name cid-data-collection \
  --query 'Stacks[0].Outputs[?OutputKey==`S3Bucket`].OutputValue' \
  --output text)

# Apply encryption
aws s3api put-bucket-encryption \
  --bucket $BUCKET_NAME \
  --server-side-encryption-configuration '{
    "Rules": [{
      "ApplyServerSideEncryptionByDefault": {
        "SSEAlgorithm": "aws:kms",
        "KMSMasterKeyID": "arn:aws:kms:us-east-1:123456789012:key/abc-123"
      },
      "BucketKeyEnabled": true
    }]
  }'
```

3. **Validate encryption:**
```bash
aws s3api get-bucket-encryption --bucket $BUCKET_NAME
```

**📖 See [ENCRYPTION_WARNING.md](ENCRYPTION_WARNING.md) for:**
- Complete implementation checklist
- Required AWS Config rules
- Risk mitigation strategies
- Monitoring setup

---

## Migration Paths

### From S3-Managed to KMS Alias

```bash
# 1. Create KMS keys and aliases (see Option 2 setup)

# 2. Update stack
aws cloudformation update-stack \
  --stack-name cid-data-collection \
  --use-previous-template \
  --parameters ParameterKey=KMSKeyAlias,ParameterValue=cid-data-collection-key \
  --capabilities CAPABILITY_NAMED_IAM
```

### From CloudFormation-Managed to External Management

```bash
# 1. Update stack to stop managing encryption
aws cloudformation update-stack \
  --stack-name cid-data-collection \
  --use-previous-template \
  --parameters ParameterKey=ManageBucketEncryption,ParameterValue=no \
  --capabilities CAPABILITY_NAMED_IAM

# 2. Apply your encryption configuration via AWS Config or automation
```

## Troubleshooting

### Q: Which option should I choose?

**A:**
- **95% of users:** Option 1 (Default)
- **Need compliance/audit:** Option 2 (KMS Alias)
- **Have AWS Config automation:** Option 3 (External) - Read warnings first!

### Q: Stack update overwrites my encryption

**A:** Set `ManageBucketEncryption: "no"` to prevent CloudFormation from managing encryption.

### Q: Access denied errors

**A:**
1. Verify `KMSKeyAlias` or `DataBucketsKmsKeysArns` is set correctly
2. Check KMS key policy allows the account
3. Ensure IAM roles have kms:Decrypt permission

### Q: Is this backward compatible?

**A:** Yes! Existing deployments continue to work without changes. All new parameters have safe defaults.

### Q: What's the cost difference?

**A:**
- Option 1 (S3-managed): $0 additional
- Option 2 (KMS): ~$3-5/month
- Option 3 (External): Depends on your setup

### Q: Can I change options later?

**A:** Yes, see Migration Paths section above.

## Additional Documentation

- ⚠️ [ENCRYPTION_WARNING.md](ENCRYPTION_WARNING.md) - Critical warnings for external management
- 📚 [ENCRYPTION_REFERENCE.md](ENCRYPTION_REFERENCE.md) - Quick reference guide

## Summary

| Option | Recommended For | CloudFormation Manages | Your Responsibility |
|--------|----------------|----------------------|-------------------|
| **Option 1: Default** | Most users | ✅ Everything | Minimal |
| **Option 2: KMS Alias** | Compliance requirements | ✅ Everything | Create keys/aliases |
| **Option 3: External** | Advanced users with automation | ❌ Encryption | ⚠️ Everything encryption-related |

**✅ Recommended:** Use Option 1 (Default) or Option 2 (KMS Alias) unless you have a specific, documented reason for external management.
