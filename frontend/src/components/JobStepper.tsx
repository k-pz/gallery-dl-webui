import { Box, Group, Stepper, Text } from "@mantine/core";
import { JOB_STEPS, type jobStep, statusTone } from "../lib/status";
import { Pill } from "./Pill";

export function JobStepper({ job }: { job: { status: string; step: ReturnType<typeof jobStep> } }) {
  const { step } = job;
  // Settled jobs collapse to a single outcome pill — the step-by-step
  // lifecycle only matters while work is still in flight.
  if (step.kind === "failed" || step.kind === "cancelled" || step.kind === "done") {
    return (
      <Group gap="xs">
        <Pill tone={statusTone(job.status)} solid noDot>
          {step.label}
        </Pill>
      </Group>
    );
  }
  const currentLabel = JOB_STEPS[Math.min(step.index, JOB_STEPS.length - 1)];
  const cancelling = step.kind === "cancelling";
  return (
    <Box className="active-job-stepper">
      <Box className="active-job-stepper-track">
        <Stepper
          active={step.index}
          size="xs"
          iconSize={20}
          color={cancelling ? "orange" : undefined}
        >
          {JOB_STEPS.map((label, i) => (
            <Stepper.Step
              key={label}
              label={label}
              loading={step.kind === "running" && i === step.index}
            />
          ))}
        </Stepper>
      </Box>
      <Text className="active-job-step-caption" size="xs" c="dimmed">
        Step {Math.min(step.index + 1, JOB_STEPS.length)} of {JOB_STEPS.length} — {currentLabel}
      </Text>
    </Box>
  );
}
