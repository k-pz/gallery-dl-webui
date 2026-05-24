import { Box, Group, Stepper, Text } from "@mantine/core";
import { JOB_STEPS, type jobStep, statusTone } from "../lib/status";
import { Pill } from "./Pill";

export function JobStepper({ job }: { job: { status: string; step: ReturnType<typeof jobStep> } }) {
  const { step } = job;
  if (step.kind === "failed" || step.kind === "cancelled") {
    return (
      <Group gap="xs">
        <Pill tone={statusTone(job.status)} solid noDot>
          {step.label}
        </Pill>
      </Group>
    );
  }
  const active = step.kind === "done" ? step.total : step.index;
  const currentIndex = step.kind === "done" ? JOB_STEPS.length - 1 : step.index;
  const currentLabel = JOB_STEPS[Math.min(currentIndex, JOB_STEPS.length - 1)];
  const cancelling = step.kind === "cancelling";
  return (
    <Box className="active-job-stepper">
      <Stepper active={active} size="xs" iconSize={20} color={cancelling ? "orange" : undefined}>
        {JOB_STEPS.map((label, i) => (
          <Stepper.Step
            key={label}
            label={label}
            loading={step.kind === "running" && i === step.index}
          />
        ))}
      </Stepper>
      <Text className="active-job-step-caption" size="xs" c="dimmed">
        Step {Math.min(currentIndex + 1, JOB_STEPS.length)} of {JOB_STEPS.length} — {currentLabel}
      </Text>
    </Box>
  );
}
