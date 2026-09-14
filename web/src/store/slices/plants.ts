import type { Plant } from '@/contracts';
import type { SliceCreator } from './types';

export type PlantsSlice = {
  plants: { byId: Record<string, Plant>; order: string[]; selected: string | null };
  setPlants: (plants: readonly Plant[]) => void;
  upsertPlant: (plant: Plant) => void;
  selectPlant: (plantId: string) => void;
};

export const createPlantsSlice: SliceCreator<PlantsSlice> = (set) => ({
  plants: { byId: {}, order: [], selected: null },
  setPlants: (plants) =>
    set((state) => {
      const byId: Record<string, Plant> = {};
      for (const plant of plants) byId[plant.plant_id] = plant;
      const order = plants.map((plant) => plant.plant_id);
      const selected =
        state.plants.selected !== null && byId[state.plants.selected]
          ? state.plants.selected
          : (order.find((id) => byId[id]?.available === true) ?? order[0] ?? null);
      return { plants: { byId, order, selected } };
    }),
  upsertPlant: (plant) =>
    set((state) => ({
      plants: {
        ...state.plants,
        byId: { ...state.plants.byId, [plant.plant_id]: plant },
        order: state.plants.order.includes(plant.plant_id)
          ? state.plants.order
          : [...state.plants.order, plant.plant_id],
      },
    })),
  selectPlant: (plantId) =>
    set((state) => ({ plants: { ...state.plants, selected: plantId } })),
});
