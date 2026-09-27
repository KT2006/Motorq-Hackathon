# Documented, not executed, due to hackathon time constraints; 
# this demonstrates the intended cloud-agnostic deployment path.

provider "aws" {
  region = "us-east-1"
}

resource "aws_ecs_cluster" "motorq_cluster" {
  name = "motorq-fleet-cluster"
}

resource "aws_ecs_task_definition" "api_task" {
  family                   = "motorq-api-task"
  network_mode             = "awsvpc"
  requires_compatibilities = ["FARGATE"]
  cpu                      = "256"
  memory                   = "512"

  container_definitions = jsonencode([
    {
      name      = "motorq-api"
      image     = "public.ecr.aws/myrepo/motorq-api:latest"
      essential = true
      portMappings = [
        {
          containerPort = 8000
          hostPort      = 8000
        }
      ]
      environment = [
        {
          name  = "POSTGRES_URL"
          value = "postgres://..."
        }
      ]
    }
  ])
}

resource "aws_ecs_service" "api_service" {
  name            = "motorq-api-service"
  cluster         = aws_ecs_cluster.motorq_cluster.id
  task_definition = aws_ecs_task_definition.api_task.arn
  desired_count   = 2
  launch_type     = "FARGATE"

  network_configuration {
    subnets          = ["subnet-xxxxxx"]
    assign_public_ip = true
  }
}
