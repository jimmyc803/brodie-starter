#!/usr/bin/env bash
set -euo pipefail
if [[ ${1:-} == --dry-run ]]; then
  printf '%s\n' 'Plan: import public SSH key; reconcile HTTPS/team-SSH security group; create private versioned backup bucket, scoped instance role and profile; resolve Ubuntu 24.04 AMI; launch/reuse EC2; attach EIP; create SNS and CPU/memory/disk/status alarms.'
  exit 0
fi
[[ $# == 0 ]] || { echo 'Usage: provision.sh [--dry-run]' >&2; exit 2; }
: "${TEAM_SSH_CIDRS:?comma-separated team CIDRs required}" "${SSH_PUBLIC_KEY_FILE:?public key path required}"
: "${BACKUP_BUCKET:?globally unique bucket name required}" "${ALERT_EMAIL:?SES/SNS team email required}"
export AWS_DEFAULT_REGION=${AWS_DEFAULT_REGION:-us-east-1}
NAME=${NAME:-brodie-challenge}
INSTANCE_TYPE=${INSTANCE_TYPE:-c7i.xlarge}
SSM_PREFIX=${SSM_PREFIX:-/brodie/challenge/}
[[ $NAME =~ ^[a-zA-Z0-9-]+$ && $SSM_PREFIX == /*/ ]] || exit 2
account=$(aws sts get-caller-identity --query Account --output text)
vpc=${VPC_ID:-$(aws ec2 describe-vpcs --filters Name=is-default,Values=true --query 'Vpcs[0].VpcId' --output text)}
[[ $vpc != None ]] || { echo 'Set VPC_ID and SUBNET_ID for an account without a default VPC' >&2; exit 1; }
if ! aws ec2 describe-key-pairs --key-names "$NAME" >/dev/null 2>&1; then
  aws ec2 import-key-pair --key-name "$NAME" --public-key-material "fileb://$SSH_PUBLIC_KEY_FILE" >/dev/null
fi
sg=$(aws ec2 describe-security-groups --filters "Name=group-name,Values=$NAME" "Name=vpc-id,Values=$vpc" --query 'SecurityGroups[0].GroupId' --output text)
if [[ $sg == None ]]; then
  sg=$(aws ec2 create-security-group --group-name "$NAME" --description 'Brodie HTTPS and team SSH' --vpc-id "$vpc" --query GroupId --output text)
fi
tmp=$(mktemp -d)
trap 'rm -rf "$tmp"' EXIT
aws ec2 describe-security-groups --group-ids "$sg" --query 'SecurityGroups[0].IpPermissions' >"$tmp/old.json"
python3 - "$TEAM_SSH_CIDRS" "$tmp" <<'PY'
import ipaddress, json, pathlib, sys
root = pathlib.Path(sys.argv[2])
rules = [{'IpProtocol': 'tcp', 'FromPort': 443, 'ToPort': 443, 'IpRanges': [{'CidrIp': '0.0.0.0/0'}]}]
for raw in sys.argv[1].split(','):
    net = ipaddress.ip_network(raw.strip(), strict=False)
    if net.prefixlen == 0:
        raise SystemExit('Team SSH must not permit the entire Internet')
    key, field = ('IpRanges', 'CidrIp') if net.version == 4 else ('Ipv6Ranges', 'CidrIpv6')
    rules.append({'IpProtocol': 'tcp', 'FromPort': 22, 'ToPort': 22, key: [{field: str(net)}]})
old = json.loads((root / 'old.json').read_text())
def flatten(permissions):
    result = []
    for rule in permissions:
        ports = {k: rule[k] for k in ('IpProtocol', 'FromPort', 'ToPort') if k in rule}
        for kind, field in [('IpRanges', 'CidrIp'), ('Ipv6Ranges', 'CidrIpv6'),
                            ('PrefixListIds', 'PrefixListId'), ('UserIdGroupPairs', 'GroupId')]:
            for entry in rule.get(kind, []):
                result.append(dict(ports, **{kind: [{field: entry[field]}]}))
    return result
old, rules = flatten(old), flatten(rules)
# Add desired permissions first so an SSH session is not interrupted on a rerun.
(root / 'add.json').write_text(json.dumps([r for r in rules if r not in old]))
(root / 'remove.json').write_text(json.dumps([r for r in old if r not in rules]))
PY
for action in add remove; do
  if [[ $(cat "$tmp/$action.json") != '[]' ]]; then
    verb=authorize; [[ $action == add ]] || verb=revoke
    aws ec2 "$verb-security-group-ingress" --group-id "$sg" --ip-permissions "file://$tmp/$action.json" >/dev/null
  fi
done
if ! aws s3api head-bucket --bucket "$BACKUP_BUCKET" --expected-bucket-owner "$account" 2>/dev/null; then
  args=(); [[ $AWS_DEFAULT_REGION == us-east-1 ]] || args=(--create-bucket-configuration "LocationConstraint=$AWS_DEFAULT_REGION")
  aws s3api create-bucket --bucket "$BACKUP_BUCKET" "${args[@]}" >/dev/null
fi
aws s3api put-public-access-block --bucket "$BACKUP_BUCKET" --public-access-block-configuration BlockPublicAcls=true,IgnorePublicAcls=true,BlockPublicPolicy=true,RestrictPublicBuckets=true
aws s3api put-bucket-versioning --bucket "$BACKUP_BUCKET" --versioning-configuration Status=Enabled
aws s3api put-bucket-encryption --bucket "$BACKUP_BUCKET" --server-side-encryption-configuration '{"Rules":[{"ApplyServerSideEncryptionByDefault":{"SSEAlgorithm":"AES256"}}]}'
printf '%s' '{"Version":"2012-10-17","Statement":[{"Effect":"Allow","Principal":{"Service":"ec2.amazonaws.com"},"Action":"sts:AssumeRole"}]}' >"$tmp/trust.json"
if ! aws iam get-role --role-name "$NAME" >/dev/null 2>&1; then
  aws iam create-role --role-name "$NAME" --assume-role-policy-document "file://$tmp/trust.json" >/dev/null
fi
python3 - "$account" "$AWS_DEFAULT_REGION" "$SSM_PREFIX" "$BACKUP_BUCKET" "$tmp/policy.json" "${SSM_KMS_KEY_ARN:-}" <<'PY'
import json, sys
account, region, prefix, bucket, dest, kms = sys.argv[1:]
statements = [
 {'Effect':'Allow','Action':['ssm:GetParametersByPath','ssm:GetParameter','ssm:GetParameters'],'Resource':f'arn:aws:ssm:{region}:{account}:parameter{prefix}*'},
 {'Effect':'Allow','Action':['s3:ListBucket'],'Resource':f'arn:aws:s3:::{bucket}'},
 {'Effect':'Allow','Action':['s3:GetObject','s3:PutObject'],'Resource':f'arn:aws:s3:::{bucket}/*'},
 {'Effect':'Allow','Action':['ses:SendEmail'],'Resource':f'arn:aws:ses:{region}:{account}:identity/*'}]
if kms:
 statements.append({'Effect':'Allow','Action':'kms:Decrypt','Resource':kms,'Condition':{'StringEquals':{'kms:ViaService':f'ssm.{region}.amazonaws.com'}}})
with open(dest, 'w') as f: json.dump({'Version':'2012-10-17','Statement':statements}, f)
PY
aws iam put-role-policy --role-name "$NAME" --policy-name brodie-runtime --policy-document "file://$tmp/policy.json"
aws iam attach-role-policy --role-name "$NAME" --policy-arn arn:aws:iam::aws:policy/CloudWatchAgentServerPolicy
if ! aws iam get-instance-profile --instance-profile-name "$NAME" >/dev/null 2>&1; then
  aws iam create-instance-profile --instance-profile-name "$NAME" >/dev/null
fi
if [[ $(aws iam get-instance-profile --instance-profile-name "$NAME" --query 'InstanceProfile.Roles[0].RoleName' --output text) == None ]]; then
  aws iam add-role-to-instance-profile --instance-profile-name "$NAME" --role-name "$NAME"
  sleep 10
fi
instance=$(aws ec2 describe-instances --filters "Name=tag:Name,Values=$NAME" Name=instance-state-name,Values=pending,running,stopping,stopped --query 'Reservations[].Instances[].InstanceId | [0]' --output text)
if [[ $instance == None ]]; then
  ami=$(aws ssm get-parameter --name /aws/service/canonical/ubuntu/server/24.04/stable/current/amd64/hvm/ebs-gp3/ami-id --query Parameter.Value --output text)
  subnet_args=(); [[ -z ${SUBNET_ID:-} ]] || subnet_args=(--subnet-id "$SUBNET_ID")
  instance=$(aws ec2 run-instances --image-id "$ami" --instance-type "$INSTANCE_TYPE" --key-name "$NAME" --security-group-ids "$sg" "${subnet_args[@]}" --iam-instance-profile "Name=$NAME" --metadata-options HttpTokens=required,HttpEndpoint=enabled --block-device-mappings '[{"DeviceName":"/dev/sda1","Ebs":{"VolumeSize":80,"VolumeType":"gp3","Encrypted":true}}]' --tag-specifications "ResourceType=instance,Tags=[{Key=Name,Value=$NAME}]" --client-token "$NAME" --query 'Instances[0].InstanceId' --output text)
fi
state=$(aws ec2 describe-instances --instance-ids "$instance" --query 'Reservations[0].Instances[0].State.Name' --output text)
if [[ $state == stopping ]]; then aws ec2 wait instance-stopped --instance-ids "$instance"; state=stopped; fi
if [[ $state == stopped ]]; then aws ec2 start-instances --instance-ids "$instance" >/dev/null; fi
aws ec2 wait instance-running --instance-ids "$instance"
aws ec2 monitor-instances --instance-ids "$instance" >/dev/null
allocation=$(aws ec2 describe-addresses --filters "Name=tag:Name,Values=$NAME" --query 'Addresses[0].AllocationId' --output text)
if [[ $allocation == None ]]; then
  allocation=$(aws ec2 allocate-address --domain vpc --tag-specifications "ResourceType=elastic-ip,Tags=[{Key=Name,Value=$NAME}]" --query AllocationId --output text)
fi
aws ec2 associate-address --instance-id "$instance" --allocation-id "$allocation" >/dev/null
topic=$(aws sns create-topic --name "$NAME-alerts" --query TopicArn --output text)
aws sns subscribe --topic-arn "$topic" --protocol email --notification-endpoint "$ALERT_EMAIL" >/dev/null
for spec in 'AWS/EC2 CPUUtilization 85' 'AWS/EC2 StatusCheckFailed 1' 'CWAgent mem_used_percent 85' 'CWAgent disk_used_percent 85'; do
  read -r namespace metric threshold <<<"$spec"
  aws cloudwatch put-metric-alarm --alarm-name "$NAME-$metric" --namespace "$namespace" --metric-name "$metric" --dimensions "Name=InstanceId,Value=$instance" --statistic Maximum --period 60 --evaluation-periods 3 --threshold "$threshold" --comparison-operator GreaterThanOrEqualToThreshold --treat-missing-data breaching --alarm-actions "$topic" --ok-actions "$topic"
done
aws ec2 describe-addresses --allocation-ids "$allocation" --query 'Addresses[0].{IP:PublicIp,Instance:InstanceId}'
