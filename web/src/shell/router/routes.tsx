import { useEffect } from 'react';
import { Route, Routes, useNavigate, useParams, useSearchParams } from 'react-router';
import { Button } from '@/components/ui/Button';
import { EmptyState } from '@/components/ui/EmptyState';
import { AppLayout } from '@/shell/layout/AppLayout';
import { Slot } from '@/shell/slots';
import { useStore } from '@/store';
import { selectedPlant } from '@/store/selectors';
import styles from './routes.module.css';

/**
 * React Router 7 in declarative (library) mode. Two routes plus a not-found.
 * Route changes never tear down the WebSocket or the store, because both live
 * above the outlet in `App`.
 */
export function AppRoutes() {
  return (
    <Routes>
      <Route element={<AppLayout />}>
        <Route index element={<PlantFloorView />} />
        <Route path="machines/:machineId" element={<MachineDetailView />} />
        <Route path="*" element={<NotFoundView />} />
      </Route>
    </Routes>
  );
}

function PlantFloorView() {
  const plant = useStore(selectedPlant);
  const setSelectedMachineId = useStore((state) => state.setSelectedMachineId);
  const navigate = useNavigate();

  useEffect(() => {
    setSelectedMachineId(null);
  }, [setSelectedMachineId]);

  // The shell owns `plant-unavailable` and renders it instead of the grid slot,
  // so T-WEB-PLANT-FLOOR never draws a second node under the same testid.
  if (plant && !plant.available) {
    return (
      <section className={styles.view}>
        <EmptyState
          area="plant-unavailable"
          testId="plant-unavailable"
          glyph="○"
          titleAs="h1"
          title={`${plant.display_name} is unavailable`}
          body={plant.unavailable_reason ?? undefined}
        />
      </section>
    );
  }

  return (
    <section className={styles.view} aria-label="Plant floor">
      <header className={styles.viewHeader}>
        <h1 className={styles.viewTitle}>
          Machines
          {plant ? (
            <span className={styles.viewCount}>
              {plant.machine_count}
              <span className={styles.srOnly}> machines in this plant</span>
            </span>
          ) : null}
        </h1>
        {plant ? (
          <Button
            data-testid="floor-demo-link"
            onClick={() => void navigate(`/machines/${plant.demo_machine_id}`)}
          >
            Open demo machine
          </Button>
        ) : null}
      </header>
      <Slot name="floor.grid" />
    </section>
  );
}

function MachineDetailView() {
  const { machineId = '' } = useParams();
  const [searchParams] = useSearchParams();
  const alertId = searchParams.get('alert');
  const machine = useStore((state) => state.machines.byId[machineId]);
  const machinesLoaded = useStore((state) => state.machines.order.length > 0);
  const setSelectedMachineId = useStore((state) => state.setSelectedMachineId);
  const setSelectedAlertId = useStore((state) => state.setSelectedAlertId);
  const navigate = useNavigate();

  useEffect(() => {
    setSelectedMachineId(machineId);
    return () => setSelectedMachineId(null);
  }, [machineId, setSelectedMachineId]);

  useEffect(() => {
    setSelectedAlertId(alertId);
  }, [alertId, setSelectedAlertId]);

  if (machinesLoaded && !machine) {
    return (
      <section className={styles.view}>
        <EmptyState
          area="machine-not-found"
          glyph="○"
          titleAs="h1"
          title={`No machine named ${machineId}`}
          body="This plant does not publish that machine. Pick one from the plant floor."
          action={<Button onClick={() => void navigate('/')}>Back to plant floor</Button>}
        />
      </section>
    );
  }

  return (
    <section
      className={styles.detail}
      data-testid="machine-detail"
      aria-label="Machine detail"
    >
      <header className={[styles.viewHeader, styles.detailHeader].join(' ')}>
        <Button variant="ghost" onClick={() => void navigate('/')}>
          ← Plant floor
        </Button>
        <h1 className={styles.viewTitle}>
          {machine?.display_name ?? machineId}
          <span className={styles.viewId}>{machineId}</span>
        </h1>
      </header>
      <div className={styles.detailGrid}>
        <div className={styles.detailPrimary}>
          <Slot name="detail.charts" />
          <Slot name="detail.whatif" />
          <Slot name="detail.compare" />
        </div>
        <div className={styles.detailSecondary}>
          <Slot name="detail.shap" />
        </div>
      </div>
    </section>
  );
}

function NotFoundView() {
  const navigate = useNavigate();
  return (
    <section className={styles.view}>
      <EmptyState
        area="route-not-found"
        glyph="○"
        titleAs="h1"
        title="That view does not exist"
        body="The dashboard has a plant floor and one page per machine."
        action={<Button onClick={() => void navigate('/')}>Back to plant floor</Button>}
      />
    </section>
  );
}
