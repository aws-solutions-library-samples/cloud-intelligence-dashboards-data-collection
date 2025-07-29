## AWS Support Case Summarization Plugin

### About

This plugin is aimed at augmenting the exerience of the AWS Support Cases Radar which is part of the [Cloud Intelligence Dashboards Framework](https://docs.aws.amazon.com/guidance/latest/cloud-intelligence-dashboards) by leveraging Generative AI powered by Amazon Bedrock to summarize AWS Support Case Communications and help customers achieve operation excellence.

This plugin contains the following elements:
* [case-summarization](README.md) - a CloudFormation Template for deploying the AWS Support Case Summarization Plugin that integrates seamlessly with the Data Collection Framework.

### Architecture

![Architecture](/plugins/support-case-summarization/images/archi.png)

### Reasonable Defaults

This plugin comes with the following reasonable defaults that can be overriden through the parameters exposed by the CloudFormation template:

| Parameter | Description | Default |
| --- | --- | --- |
| BedrockRegion | The AWS Region from which the Summarization is performed | us-east-1 |
| Instructions | Additional instructions passed to the Large Language Model for the summarization process customizability | '' |
| Provider | Large Language Model Provider for the summarization process customizability | Anthropic |
| FoundationModel | Foundation Model to be used for the summarization process | Claude 3.5 Sonnet |
| InferenceType | Summarization process Inference Type | 'ON_DEMAND' |
| Temperature | Summarization process Temperature | 0 |
| MaxTokens | Summarization process Maximum Tokens | 8096 |
| MaxRetries | Summarization process Maximum Retries | 30 |
| Timeout | Summarization process Timeout in seconds | 60 |
| BatchSize | Summarization process Batch Size for parallel processing | 1 |

### Installation

#### 1. Enable Amazon Bedrock Target Model Access In the Data Collection Account

- See [Add or remove access to Amazon Bedrock foundation models](https://docs.aws.amazon.com/bedrock/latest/userguide/model-access-modify.html) for guidance.

#### 2. Deploy the AWS Support Case Summarization Stack In the Data Collection Account

    * <kbd> <br> [Launch Stack >>](https://console.aws.amazon.com/cloudformation/home#/stacks/create/review?&templateURL=https://aws-managed-cost-intelligence-dashboards.s3.amazonaws.com/cfn/case-summarization/case-summarization.yaml&stackName=CidSupportCaseSummarizationStack)  <br> </kbd>


## Guardrail

See [GUARDRAIL](GUARDRAIL.md) for more information.


## Support and Contribution

See [CONTRIBUTING](CONTRIBUTING.md) for more information.

## Security

See [SECURITY](SECURITY.md) for more information.

## Limitations

As of today, the AWS Support Cases Summarization plugin does not make use of Amazon Bedrock Guardrails. See [issue](https://github.com/run-llama/llama_index/issues/17217).

## License

This project is licensed under the Apache-2.0 License.
