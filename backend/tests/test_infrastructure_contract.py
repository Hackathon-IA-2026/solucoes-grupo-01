import tomllib
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]


class CloudFormationLoader(yaml.SafeLoader):
    pass


def construct_intrinsic(loader: CloudFormationLoader, tag_suffix: str, node: yaml.Node):
    key = f"Fn::{tag_suffix}" if tag_suffix != "Ref" else "Ref"
    if isinstance(node, yaml.ScalarNode):
        value = loader.construct_scalar(node)
    elif isinstance(node, yaml.SequenceNode):
        value = loader.construct_sequence(node)
    elif isinstance(node, yaml.MappingNode):
        value = loader.construct_mapping(node)
    else:
        raise TypeError(f"Nó CloudFormation não suportado: {type(node).__name__}")
    return {key: value}


CloudFormationLoader.add_multi_constructor("!", construct_intrinsic)


def load_template() -> dict:
    return yaml.load((ROOT / "template.yaml").read_text(), Loader=CloudFormationLoader)


def test_sam_manages_frontend_website_and_public_read_policy() -> None:
    template = load_template()
    resources = template["Resources"]
    bucket = resources["FrontendBucket"]
    policy = resources["FrontendBucketPolicy"]

    assert bucket["Type"] == "AWS::S3::Bucket"
    assert bucket["DeletionPolicy"] == "Retain"
    assert bucket["UpdateReplacePolicy"] == "Retain"
    assert bucket["Properties"]["WebsiteConfiguration"] == {
        "IndexDocument": "index.html",
        "ErrorDocument": "index.html",
    }
    assert bucket["Properties"]["PublicAccessBlockConfiguration"] == {
        "BlockPublicAcls": True,
        "IgnorePublicAcls": True,
        "BlockPublicPolicy": False,
        "RestrictPublicBuckets": False,
    }
    assert policy["Type"] == "AWS::S3::BucketPolicy"
    assert policy["Properties"]["Bucket"] == {"Ref": "FrontendBucket"}


def test_sam_exposes_frontend_bucket_and_website_url() -> None:
    template = load_template()
    outputs = template["Outputs"]

    assert outputs["FrontendBucketName"]["Value"] == {"Ref": "FrontendBucket"}
    assert "FrontendWebsiteUrl" in outputs
    api_environment = template["Resources"]["ApiFunction"]["Properties"]["Environment"]["Variables"]
    cors_origins = api_environment["CORS_ORIGINS"]["Fn::Join"][1]
    assert {
        "Fn::Sub": "http://${FrontendBucket}.s3-website-${AWS::Region}.${AWS::URLSuffix}"
    } in cors_origins
    assert "AllowedOrigin" not in template["Parameters"]


def test_api_can_persist_decisions_and_invoke_bedrock_converse() -> None:
    properties = load_template()["Resources"]["ApiFunction"]["Properties"]
    variables = properties["Environment"]["Variables"]
    policies = properties["Policies"]

    assert variables["SCENARIOS_TABLE"] == {"Ref": "ScenariosTable"}
    assert variables["EXPOSURE_TABLE"] == {"Ref": "ExposureTable"}
    assert variables["PUBLIC_DATA_MAX_AGE_HOURS"] == "48"
    assert {"DynamoDBCrudPolicy": {"TableName": {"Ref": "ScenariosTable"}}} in policies
    statements = next(policy["Statement"] for policy in policies if "Statement" in policy)
    invoke = next(statement for statement in statements if statement["Sid"] == "InvokeBedrockModel")
    assert "bedrock:InvokeModel" in invoke["Action"]


def test_sam_provisions_retained_exposure_narratives_without_a_schedule() -> None:
    template = load_template()
    resources = template["Resources"]
    table = resources["ExposureNarrativesTable"]
    properties = table["Properties"]
    api = resources["ApiFunction"]["Properties"]

    assert table["DeletionPolicy"] == "Retain"
    assert table["UpdateReplacePolicy"] == "Retain"
    assert properties["BillingMode"] == "PAY_PER_REQUEST"
    assert properties["KeySchema"] == [
        {"AttributeName": "asset_id", "KeyType": "HASH"},
        {"AttributeName": "version", "KeyType": "RANGE"},
    ]
    assert properties["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"] is True
    assert properties["SSESpecification"]["SSEEnabled"] is True
    assert api["Environment"]["Variables"]["EXPOSURE_NARRATIVES_TABLE"] == {
        "Ref": "ExposureNarrativesTable"
    }
    assert {"DynamoDBReadPolicy": {"TableName": {"Ref": "ExposureNarrativesTable"}}} in api[
        "Policies"
    ]
    assert template["Outputs"]["ExposureNarrativesTableName"]["Value"] == {
        "Ref": "ExposureNarrativesTable"
    }
    assert not any("Schedule" in resource["Type"] for resource in resources.values())


def test_sam_provisions_retained_encrypted_ingestion_ledger() -> None:
    resources = load_template()["Resources"]
    table = resources["IngestionLedgerTable"]

    assert table["Type"] == "AWS::DynamoDB::Table"
    assert table["DeletionPolicy"] == "Retain"
    assert table["UpdateReplacePolicy"] == "Retain"
    properties = table["Properties"]
    assert properties["BillingMode"] == "PAY_PER_REQUEST"
    assert properties["AttributeDefinitions"] == [
        {"AttributeName": "source_fingerprint", "AttributeType": "S"}
    ]
    assert properties["KeySchema"] == [{"AttributeName": "source_fingerprint", "KeyType": "HASH"}]
    assert properties["PointInTimeRecoverySpecification"]["PointInTimeRecoveryEnabled"] is True
    assert properties["SSESpecification"]["SSEEnabled"] is True
    assert load_template()["Outputs"]["IngestionLedgerTableName"]["Value"] == {
        "Ref": "IngestionLedgerTable"
    }


def test_ingestion_functions_use_ledger_and_all_registered_ons_dataset_prefixes() -> None:
    resources = load_template()["Resources"]
    discovery = resources["IngestionDiscoveryFunction"]["Properties"]
    copy = resources["IngestionCopyFunction"]["Properties"]

    for function in (discovery, copy):
        variables = function["Environment"]["Variables"]
        assert variables["INGESTION_LEDGER_TABLE"] == {"Ref": "IngestionLedgerTable"}
        assert variables["INGESTION_LEASE_SECONDS"] == "300"
        assert {"DynamoDBCrudPolicy": {"TableName": {"Ref": "IngestionLedgerTable"}}} in function[
            "Policies"
        ]

    list_statement = discovery["Policies"][-1]["Statement"][0]
    assert list_statement["Action"] == ["s3:ListBucket"]
    assert list_statement["Condition"]["StringLike"]["s3:prefix"] == ["dataset/*"]
    read_statement = copy["Policies"][-1]["Statement"][0]
    assert read_statement["Action"] == ["s3:GetObject"]
    assert read_statement["Resource"] == {
        "Fn::Sub": "arn:${AWS::Partition}:s3:::${OnsSourceBucket}/dataset/*"
    }


def test_sam_decouples_copy_and_materialization_with_encrypted_sqs() -> None:
    template = load_template()
    resources = template["Resources"]
    queue = resources["MaterializationQueue"]["Properties"]
    dead_letter_queue = resources["MaterializationDeadLetterQueue"]["Properties"]
    copy = resources["IngestionCopyFunction"]["Properties"]
    materialization = resources["ExposureMaterializationFunction"]["Properties"]

    assert queue["SqsManagedSseEnabled"] is True
    assert dead_letter_queue["SqsManagedSseEnabled"] is True
    assert queue["VisibilityTimeout"] > materialization["Timeout"]
    assert queue["RedrivePolicy"] == {
        "deadLetterTargetArn": {"Fn::GetAtt": "MaterializationDeadLetterQueue.Arn"},
        "maxReceiveCount": 3,
    }
    copy_variables = copy["Environment"]["Variables"]
    assert copy_variables["MATERIALIZATION_QUEUE_URL"] == {"Ref": "MaterializationQueue"}
    assert "MATERIALIZATION_FUNCTION" not in copy_variables
    assert {
        "SQSSendMessagePolicy": {"QueueName": {"Fn::GetAtt": "MaterializationQueue.QueueName"}}
    } in copy["Policies"]
    assert not any(
        "lambda:InvokeFunction" in statement.get("Action", [])
        for policy in copy["Policies"]
        for statement in policy.get("Statement", [])
    )

    variables = materialization["Environment"]["Variables"]
    assert variables["DATA_BUCKET"] == {"Ref": "DataBucket"}
    assert variables["INGESTION_LEDGER_TABLE"] == {"Ref": "IngestionLedgerTable"}
    assert variables["INGESTION_LEASE_SECONDS"] == "300"
    assert {
        "DynamoDBCrudPolicy": {"TableName": {"Ref": "IngestionLedgerTable"}}
    } in materialization["Policies"]
    event = materialization["Events"]["MaterializationQueueEvent"]
    assert event["Type"] == "SQS"
    assert event["Properties"]["Queue"] == {"Fn::GetAtt": "MaterializationQueue.Arn"}
    assert event["Properties"]["FunctionResponseTypes"] == ["ReportBatchItemFailures"]
    assert template["Outputs"]["MaterializationQueueUrl"]["Value"] == {
        "Ref": "MaterializationQueue"
    }


def test_sam_keeps_the_legacy_frontend_origin_during_migration() -> None:
    template = load_template()
    api_environment = template["Resources"]["ApiFunction"]["Properties"]["Environment"]["Variables"]
    cors_origins = api_environment["CORS_ORIGINS"]["Fn::Join"][1]

    legacy_origin = "http://curtailess-frontend-290278850174-us-west-2." + (
        "s3-website-us-west-2.amazonaws.com"
    )
    assert legacy_origin in cors_origins
    assert {
        "Fn::Sub": "http://${FrontendBucket}.s3-website-${AWS::Region}.${AWS::URLSuffix}"
    } in cors_origins


def test_samconfig_centralizes_non_secret_deploy_parameters() -> None:
    config = tomllib.loads((ROOT / "samconfig.toml").read_text())
    deploy = config["default"]["deploy"]["parameters"]

    assert deploy["stack_name"] == "curtailess-dev"
    assert deploy["region"] == "us-west-2"
    assert deploy["resolve_s3"] is True
    assert "CAPABILITY_IAM" in deploy["capabilities"]
    assert "profile" not in deploy
    serialized = (ROOT / "samconfig.toml").read_text().upper()
    assert "AWS_ACCESS_KEY_ID" not in serialized
    assert "AWS_SECRET_ACCESS_KEY" not in serialized
    assert "AWS_SESSION_TOKEN" not in serialized


def test_frontend_deploy_discovers_stack_outputs() -> None:
    script = (ROOT / "frontend" / "scripts" / "deploy-s3.sh").read_text()

    assert "stack_output FrontendBucketName" in script
    assert "stack_output ApiUrl" in script
    assert "stack_output FrontendWebsiteUrl" in script
    assert 'VITE_API_BASE_URL="${api_url}" npm run build' in script
    assert 'aws s3 sync build/client "s3://${bucket}" --delete' in script
