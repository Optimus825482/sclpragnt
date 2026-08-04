export type IndicatorStyle = {
  colors: string[];
  lineWidth: number;
  showPriceLine: boolean;
  showBounds: boolean;
  minValue?: number | null;
  maxValue?: number | null;
};

export type IndicatorInstance = {
  uid: string;
  registryId: string;
  name: string;
  overlay: boolean;
  params: Record<string, any>;
  style: IndicatorStyle;
};

export type InputConfig = {
  id: string;
  type: string;
  title: string;
  defval: any;
  min?: number;
  max?: number;
  step?: number;
  options?: string[];
};

export type RegistryEntry = {
  id: string;
  name: string;
  shortName: string;
  category: string;
  group: string;
  overlay: boolean;
  inputConfig: InputConfig[];
  calculate: (
    bars: any[],
    params: any,
  ) => {
    metadata: { overlay: boolean };
    plots: Record<
      string,
      { time: number; value: number | null; color?: string }[]
    >;
  };
};
