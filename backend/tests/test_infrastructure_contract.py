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
    assert api_environment["CORS_ORIGINS"] == {
        "Fn::Sub": "http://${FrontendBucket}.s3-website-${AWS::Region}.${AWS::URLSuffix}"
    }
    assert "AllowedOrigin" not in template["Parameters"]


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
