import { fireEvent, render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { axe } from 'vitest-axe';
import { Badge } from '../Badge';
import { Button } from '../Button';
import { EmptyState } from '../EmptyState';
import { ErrorState } from '../ErrorState';
import { HealthRing } from '../HealthRing';
import { IconButton } from '../IconButton';
import { Select } from '../Select';
import { Skeleton } from '../Skeleton';
import { Slider } from '../Slider';
import { Sparkline } from '../Sparkline';
import { Tooltip } from '../Tooltip';

describe('Button', () => {
  it('is a real button, clickable and keyboard-operable', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<Button onClick={onClick}>Open demo machine</Button>);

    const button = screen.getByRole('button', { name: 'Open demo machine' });
    await user.click(button);
    button.focus();
    await user.keyboard('{Enter}');
    await user.keyboard(' ');
    expect(onClick).toHaveBeenCalledTimes(3);
  });

  it('does not fire while disabled', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(
      <Button variant="primary" disabled onClick={onClick}>
        Commit
      </Button>,
    );
    await user.click(screen.getByRole('button', { name: 'Commit' }));
    expect(onClick).not.toHaveBeenCalled();
  });
});

describe('IconButton', () => {
  it('has an accessible name even though it renders only a glyph', async () => {
    const user = userEvent.setup();
    const onClick = vi.fn();
    render(<IconButton label="Close alerts" glyph="✕" onClick={onClick} />);

    await user.click(screen.getByRole('button', { name: 'Close alerts' }));
    expect(onClick).toHaveBeenCalledOnce();
  });
});

describe('Select', () => {
  it('is a native select with a label and reports changes', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Select
        label="Plant"
        onChange={onChange}
        value="ai4i"
        options={[
          { value: 'ai4i', label: 'AI4I 2020 Milling Plant' },
          { value: 'ims', label: 'NASA IMS Bearing Test Rig' },
        ]}
      />,
    );

    const select = screen.getByRole('combobox', { name: 'Plant' });
    await user.selectOptions(select, 'ims');
    expect(onChange).toHaveBeenCalledOnce();
  });

  it('disables an unavailable option rather than hiding it', () => {
    render(
      <Select
        label="Plant"
        defaultValue="ai4i"
        options={[
          { value: 'ai4i', label: 'AI4I' },
          { value: 'ims', label: 'IMS', disabled: true },
        ]}
      />,
    );
    expect(screen.getByRole('option', { name: 'IMS' })).toBeDisabled();
  });
});

describe('Slider', () => {
  it('exposes the backend unit string in aria-valuetext and moves with the keyboard', async () => {
    const user = userEvent.setup();
    const onChange = vi.fn();
    render(
      <Slider
        label="Torque — 95th pct over 4 h"
        valueText="48.1 N·m"
        min={0}
        max={80}
        step={0.1}
        defaultValue={48.1}
        onChange={onChange}
      />,
    );

    const slider = screen.getByRole('slider', { name: 'Torque — 95th pct over 4 h' });
    expect(slider).toHaveAttribute('aria-valuetext', '48.1 N·m');
    // A native range input carries keyboard support; jsdom does not implement
    // its key handling, so the change it would emit is asserted directly.
    await user.tab();
    expect(slider).toHaveFocus();
    fireEvent.change(slider, { target: { value: '48.2' } });
    expect(onChange).toHaveBeenCalled();
  });

  it('renders an optional hint row', () => {
    render(<Slider label="Feature" valueText="1" hint="original 0.8" />);
    expect(screen.getByText('original 0.8')).toBeInTheDocument();
  });
});

describe('Tooltip', () => {
  it('opens on focus as well as hover, and closes on Escape', async () => {
    const user = userEvent.setup();
    render(
      <Tooltip content="last frame received 10:45:00">
        {(props) => (
          <button type="button" {...props}>
            connection
          </button>
        )}
      </Tooltip>,
    );

    const trigger = screen.getByRole('button', { name: 'connection' });
    await user.hover(trigger);
    expect(screen.getByRole('tooltip')).toHaveTextContent('last frame received');

    await user.unhover(trigger);
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();

    await user.tab();
    expect(trigger).toHaveFocus();
    expect(screen.getByRole('tooltip')).toBeInTheDocument();
    expect(trigger).toHaveAttribute('aria-describedby');

    await user.keyboard('{Escape}');
    expect(screen.queryByRole('tooltip')).not.toBeInTheDocument();
  });
});

describe('Sparkline', () => {
  it('breaks the path at nulls instead of dropping to the baseline', () => {
    render(
      <Sparkline
        label="risk, last 60 ticks"
        data-testid="tile-sparkline-ai4i-03"
        values={[null, null, 0.2, 0.4, null, 0.6, 0.8]}
      />,
    );
    const paths = screen.getByTestId('tile-sparkline-ai4i-03').querySelectorAll('path');
    // Two subpaths: the leading nulls start the line late and the interior null
    // splits it, with no coordinate interpolated across the gap.
    expect(paths).toHaveLength(2);
  });

  it('renders its empty treatment, not a flat zero line, for an all-null series', () => {
    render(
      <Sparkline label="risk" data-testid="tile-sparkline-ims-04" values={[null, null]} />,
    );
    const svg = screen.getByTestId('tile-sparkline-ims-04');
    expect(svg.querySelectorAll('path')).toHaveLength(0);
    expect(svg.querySelector('line')).toBeInTheDocument();
  });

  it('clamps a sample outside the domain to the axis edge', () => {
    render(<Sparkline label="risk" data-testid="spark" values={[2, 0.5]} />);
    const d = screen.getByTestId('spark').querySelector('path')?.getAttribute('d') ?? '';
    expect(d.startsWith('M0.00,0.00')).toBe(true);
  });
});

describe('HealthRing', () => {
  it('renders the percentage when scored', () => {
    render(
      <HealthRing probability={0.74} label="risk 74%" data-testid="tile-ring-ai4i-03" />,
    );
    expect(screen.getByTestId('tile-ring-ai4i-03')).toHaveTextContent('74%');
    expect(screen.getByTestId('tile-ring-ai4i-03').querySelectorAll('circle')).toHaveLength(
      2,
    );
  });

  it('renders the designed not-yet-scored state for a null probability', () => {
    render(
      <HealthRing
        probability={null}
        label="not yet scored"
        data-testid="tile-ring-ims-04"
      />,
    );
    const ring = screen.getByTestId('tile-ring-ims-04');
    expect(ring).toHaveTextContent('—');
    // Empty track, no filled arc — never a zero-length arc labelled 0%.
    expect(ring.querySelectorAll('circle')).toHaveLength(1);
    expect(ring).not.toHaveTextContent('0%');
  });
});

describe('Badge, Skeleton, EmptyState, ErrorState', () => {
  it('encodes state with a glyph as well as a colour', () => {
    render(
      <Badge tone="danger" glyph="▲" data-testid="alert-severity-high">
        HIGH
      </Badge>,
    );
    const badge = screen.getByTestId('alert-severity-high');
    expect(badge).toHaveTextContent('▲');
    expect(badge).toHaveTextContent('HIGH');
  });

  it('matches the final geometry while loading', () => {
    render(<Skeleton area="machine-grid" width={200} height={132} />);
    const skeleton = screen.getByTestId('skeleton-machine-grid');
    expect(skeleton).toHaveStyle({ width: '200px', height: '132px' });
  });

  it('renders a designed empty state with an accessible action', async () => {
    const onClick = vi.fn();
    const user = userEvent.setup();
    const { container } = render(
      <EmptyState
        area="alert-feed"
        title="No alerts yet"
        body="Alerts arrive here as the model flags machines."
        action={<Button onClick={onClick}>Open demo machine</Button>}
      />,
    );

    expect(screen.getByTestId('empty-alert-feed')).toHaveTextContent('No alerts yet');
    await user.click(screen.getByRole('button', { name: 'Open demo machine' }));
    expect(onClick).toHaveBeenCalledOnce();
    await expect(axe(container)).resolves.toHaveNoViolations();
  });

  it('announces an error state through role=alert', () => {
    render(<ErrorState area="connection" title="Lost the API" detail="503" />);
    expect(screen.getByRole('alert')).toHaveTextContent('Lost the API');
    expect(screen.getByTestId('error-connection')).toHaveTextContent('503');
  });
});
