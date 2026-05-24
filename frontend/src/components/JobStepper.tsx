import { Group, Stepper } from "@mantine/core";
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
  return (
    <Stepper
      active={active}
      size="xs"
      iconSize={20}
      color={step.kind === "cancelling" ? "orange" : undefined}
    >
      {JOB_STEPS.map((label, i) => (
        <Stepper.Step
          key={label}
          label={label}
          loading={step.kind === "running" && i === step.index}
        />
      ))}
    </Stepper>
  );
}
