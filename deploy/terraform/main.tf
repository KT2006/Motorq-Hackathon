# Fleet Intelligence Platform — AWS Deployment
#
# Documented infrastructure-as-code for the intended cloud deployment.
# NOTE: Not executed during the hackathon due to time constraints.
# This demonstrates the cloud-native deployment path on AWS ECS Fargate.
#
# Prerequisites:
#   - AWS CLI configured with appropriate IAM role
#   - Docker images pushed to ECR
#   - VPC and subnets configured
#
# Usage:
#   terraform init
#   terraform plan -var-file=production.tfvars
#   terraform apply

terraform {
  required_version = ">= 1.5"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
  }
}

variable "region" {
  default = "ap-south-1"  # Mumbai — closest to demo (Chennai data)
}

variable "vpc_id" {
  description = "VPC ID for deployment"
  type        = string
}

variable "subnet_ids" {
  description = "Subnet IDs for Fargate tasks"
  type        = list(string)
}

variable "api_image" {
  default = "motorq-api:latest"
}

variable "ingestion_image" {
  default = "motorq-ingestion:latest"
}

variable "dashboard_image" {
  default = "motorq-dashboard:latest"
}

provider "aws" {
  region = var.region
}

# ---------- ECS Cluster ----------

resource "aws_ecs_cluster" "motorq" {
  name = "motorq-fleet-cluster"

  setting {
    name  = "containerInsights"
    value = "enabled"
  }
}

# ---------- IAM ----------

resource "aws_iam_role" "ecs_execution" {
  name = "motorq-ecs-execution"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Action    = "sts:AssumeRole"
      Effect    = "Allow"
      Principal = { Service = "ecs-tasks.amazonaws.com" }
    }]
  })
}

resource "aws_iam_role_policy_attachment" "ecs_execution" {
  role       = aws_iam_role.ecs_execution.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AmazonECSTaskExecutionRolePolicy"
}

# ---------- Secrets ----------

resource "aws_secretsmanager_secret" "motorq_secrets" {
  name = "motorq/fleet-secrets"
}

# ---------- API Task ----------

resource "aws_ecs_task_definition" "api" {
  family                   = "motorq-api"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "512"
  memory                   = "1024"
  execution_role_arn       = aws_iam_role.ecs_execution.arn

  container_definitions = jsonencode([{
    name      = "motorq-api"
    image     = var.api_image
    essential = true
    portMappings = [{
      containerPort = 8000
      hostPort      = 8000
      protocol      = "tcp"
    }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/motorq-api"
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "api"
      }
    }
    healthCheck = {
      command     = ["CMD-SHELL", "curl -sf http://localhost:8000/health || exit 1"]
      interval    = 30
      timeout     = 5
      retries     = 3
      startPeriod = 15
    }
    secrets = [{
      name      = "POSTGRES_URL"
      valueFrom = "${aws_secretsmanager_secret.motorq_secrets.arn}:POSTGRES_URL::"
    }, {
      name      = "JWT_SECRET"
      valueFrom = "${aws_secretsmanager_secret.motorq_secrets.arn}:JWT_SECRET::"
    }, {
      name      = "GROQ_API_KEY"
      valueFrom = "${aws_secretsmanager_secret.motorq_secrets.arn}:GROQ_API_KEY::"
    }]
  }])
}

resource "aws_ecs_service" "api" {
  name            = "motorq-api"
  cluster         = aws_ecs_cluster.motorq.id
  task_definition = aws_ecs_task_definition.api.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.subnet_ids
    assign_public_ip = true
  }
}

# ---------- Ingestion Task ----------

resource "aws_ecs_task_definition" "ingestion" {
  family                   = "motorq-ingestion"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn

  container_definitions = jsonencode([{
    name      = "motorq-ingestion"
    image     = var.ingestion_image
    essential = true
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/motorq-ingestion"
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "ingestion"
      }
    }
    secrets = [{
      name      = "POSTGRES_URL"
      valueFrom = "${aws_secretsmanager_secret.motorq_secrets.arn}:POSTGRES_URL::"
    }]
  }])
}

resource "aws_ecs_service" "ingestion" {
  name            = "motorq-ingestion"
  cluster         = aws_ecs_cluster.motorq.id
  task_definition = aws_ecs_task_definition.ingestion.arn
  desired_count   = 3  # Multiple consumers for throughput
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.subnet_ids
    assign_public_ip = false
  }
}

# ---------- Dashboard Task ----------

resource "aws_ecs_task_definition" "dashboard" {
  family                   = "motorq-dashboard"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"
  execution_role_arn       = aws_iam_role.ecs_execution.arn

  container_definitions = jsonencode([{
    name      = "motorq-dashboard"
    image     = var.dashboard_image
    essential = true
    portMappings = [{
      containerPort = 80
      hostPort      = 80
      protocol      = "tcp"
    }]
    logConfiguration = {
      logDriver = "awslogs"
      options = {
        "awslogs-group"         = "/ecs/motorq-dashboard"
        "awslogs-region"        = var.region
        "awslogs-stream-prefix" = "dashboard"
      }
    }
  }])
}

resource "aws_ecs_service" "dashboard" {
  name            = "motorq-dashboard"
  cluster         = aws_ecs_cluster.motorq.id
  task_definition = aws_ecs_task_definition.dashboard.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = var.subnet_ids
    assign_public_ip = true
  }
}

# ---------- Outputs ----------

output "cluster_name" {
  value = aws_ecs_cluster.motorq.name
}
