import pulumi
import pulumi_aws as aws
import pulumi_docker as docker

region = aws.config.region
cluster_name = "rust-fargate-cluster"

cluster = aws.ecs.Cluster(cluster_name)

repo = aws.ecr.Repository("rust-microservice-repo")

image = docker.Image(
    "rust-microservice",
     build=docker.DockerBuildArgs(
        context="../",
        platform="linux/amd64",
    ),
    image_name=repo.repository_url.apply(lambda url: f"{url}:latest"),
    registry=repo.registry_id.apply(lambda reg: {
        "server": repo.repository_url,
        "username": aws.ecr.get_authorization_token().user_name,
        "password": aws.ecr.get_authorization_token().password,
    }),
)

execution_role = aws.iam.Role("ecsTaskExecutionRole",
    assume_role_policy=pulumi.Output.json_dumps({
        "Version": "2012-10-17",
        "Statement": [{
            "Action": "sts:AssumeRole",
            "Effect": "Allow",
            "Principal": {"Service": "ecs-tasks.amazonaws.com"},
        }]
    })
)

aws.iam.RolePolicyAttachment("ecsTaskExecutionRolePolicy",
    role=execution_role.name,
    policy_arn="arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
)

log_group = aws.cloudwatch.LogGroup("rust-log-group",
    retention_in_days=7
)

task_def = aws.ecs.TaskDefinition("rust-microservice-task",
    family="rust-microservice",
    cpu="256",
    memory="512",
    network_mode="awsvpc",
    requires_compatibilities=["FARGATE"],
    execution_role_arn=execution_role.arn,
    container_definitions=pulumi.Output.json_dumps([{
        "name": "rust-microservice",
        "image": image.image_name,
        "memory": 512,
        "cpu": 256,
        "essential": True,
        "portMappings": [{"containerPort": 8080, "hostPort": 8080}],
        "logConfiguration": {
            "logDriver": "awslogs",
            "options": {
                "awslogs-group": log_group.name,
                "awslogs-region": region,
                "awslogs-stream-prefix": "rust"
            }
        }
    }])
)

security_group = aws.ec2.SecurityGroup("rust-service-sg",
    ingress=[{
        "protocol": "tcp",
        "from_port": 8080,
        "to_port": 8080,
        "cidr_blocks": ["0.0.0.0/0"],
    },
    {
        "protocol": "tcp",
        "from_port": 80,  # ALB port
        "to_port": 80,
        "cidr_blocks": ["0.0.0.0/0"],
    }],
     egress=[{
        "protocol": "-1",
        "from_port": 0,  # Allow outbound traffic to ECR
        "to_port": 0,
        "cidr_blocks": ["0.0.0.0/0"],  # Allow outbound to the internet
    }]
)

# Fetch default VPC and subnets
vpc = aws.ec2.get_vpc(default=True)
subnets = aws.ec2.get_subnets(filters=[{"name": "vpc-id", "values": [vpc.id]}])

eip = aws.ec2.Eip("nat-eip", vpc=True)

nat_gateway = aws.ec2.NatGateway("rust-nat-gateway",
    allocation_id=eip.id,
    subnet_id=subnets.ids[0],  # Choose the public subnet
)

# Create an Application Load Balancer (ALB)
alb = aws.lb.LoadBalancer("rust-alb",
    internal=False,
    security_groups=[security_group.id],
    subnets=subnets.ids
)

# Create a Target Group for the ALB
target_group = aws.lb.TargetGroup("rust-target-group",
    port=8080,
    protocol="HTTP",
    target_type="ip",
    vpc_id=vpc.id,
    health_check={
        "path": "/health",  # assuming you have a health check endpoint
        "interval": 30,
        "timeout": 5,
        "healthy_threshold": 3,
        "unhealthy_threshold": 3
    }
)

# Create an ALB Listener
listener = aws.lb.Listener("rust-listener",
    load_balancer_arn=alb.arn,
    port=80,
    protocol="HTTP",
    default_actions=[{
        "type": "forward",
        "target_group_arn": target_group.arn
    }]
)

# Create a Fargate Service
service = aws.ecs.Service("rust-microservice-service",
    cluster=cluster.arn,
    task_definition=task_def.arn,
    launch_type="FARGATE",
    desired_count=1,
    network_configuration={
        "assignPublicIp": True,
        "securityGroups": [security_group.id],
        "subnets": subnets.ids,
    },
    load_balancers=[{
        "target_group_arn": target_group.arn,
        "container_name": "rust-microservice",
        "container_port": 8080
    }],
)



scaling_target = aws.appautoscaling.Target("rust-scaling-target",
    max_capacity=10,
    min_capacity=1,
    resource_id=service.id.apply(lambda id: f"service/{cluster.name}/{id}"),
    scalable_dimension="ecs:service:DesiredCount",
    service_namespace="ecs"
)

scaling_policy = aws.appautoscaling.Policy("rust-scaling-policy",
    policy_type="TargetTrackingScaling",
    resource_id=scaling_target.resource_id,
    scalable_dimension=scaling_target.scalable_dimension,
    service_namespace=scaling_target.service_namespace,
    target_tracking_scaling_policy_configuration={
        "targetValue": 60.0,
        "predefinedMetricSpecification": {
            "predefinedMetricType": "ECSServiceAverageCPUUtilization"
        },
        "scaleInCooldown": 300,
        "scaleOutCooldown": 300
    }
)

# Output the ALB DNS name
pulumi.export("alb_dns_name", alb.dns_name)

