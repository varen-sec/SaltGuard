"""Only informational, software-simulated soil indicator alerts.
Never used to control water source, pump, valves or agronomic treatment.
"""
from __future__ import annotations

def soil_alerts(config, world):
    results=[]
    for i, z in enumerate(config['zones'],1):
        pairs=[('soil_ec_z'+str(i)+'_ds_m','EC đất',z.get('soil_ec_max'),'max','dS/m'),
               ('soil_na_z'+str(i)+'_mg_kg','Na đất',z.get('soil_na_max'),'max','mg/kg'),
               ('soil_ph_z'+str(i),'pH đất',z.get('soil_ph_min'),'min','pH'),
               ('soil_ph_z'+str(i),'pH đất',z.get('soil_ph_max'),'max','pH')]
        for key,label,limit,op,unit in pairs:
            value=world.get(key)
            if limit is None or not isinstance(value,(int,float)):continue
            triggered=(value>limit if op=='max' else value<limit)
            if triggered:
                results.append({'level':'warning','kind':'SOIL_MONITOR',
                    'title':f'{z["name"]}: {label} ngoài ngưỡng theo dõi',
                    'detail':f'Chỉ số mô phỏng {value:g} {unit}; ngưỡng được cấu hình {limit:g} {unit}.',
                    'human_action':'Để người trồng và kỹ sư đánh giá; SaltGuard không tự xử lý đất.',
                    'zone':i,'alert_key':f'soil:{i}:{key}:{op}'})
    return results

