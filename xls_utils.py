import xlsxwriter
import pandas as pd
import datetime


def xls_create_occupancy_charts(res, folder, capacity_dimension):

    writer = pd.ExcelWriter('{}/occupancy.xlsx'.format(folder), engine='xlsxwriter')
    workbook = writer.book
    chart = workbook.add_chart({'type': 'scatter'})
    chart_bar = workbook.add_chart({'type': 'column'})
    chart_time_bar = workbook.add_chart({'type': 'column'})

    for i, occupancy_stamps in enumerate(res.get('occupancy')):
        df = pd.DataFrame(occupancy_stamps, columns=['time', 'v{}_onboard'.format(i)])
        df.replace(to_replace=-1, value=0, inplace=True)

        def pr(sec):
            hours = sec // 3600
            minutes = (sec // 60) - (hours * 60)
            return datetime.time(hour=int(hours), minute=int(minutes))

        df['time'] = df.time.apply(pr)
        # print(df)
        df.to_excel(writer, sheet_name='vehicle{}'.format(i), index=False)
        worksheet = writer.sheets['vehicle{}'.format(i)]
        time_format = workbook.add_format({'num_format': 'hh:mm'})
        for row, t in enumerate(df.time.iteritems(), start=2):
            worksheet.write_datetime('A{}'.format(row), t[1], time_format)

        chart.add_series({'name':       'vehicle{}'.format(i),
                          'categories': '=vehicle{}!$A$2:$A${}'.format(i, len(occupancy_stamps)+3),
                          'values':     '=vehicle{}!$B$2:$B${}'.format(i, len(occupancy_stamps)+3),
                          'marker':     {'type': 'circle', 'size': 3}})

        # ************** bar_seconds chart ****************
        time_bar = [0 for _ in range(capacity_dimension + 1)]
        idle_bar = 0
        for stamp1, stamp2 in zip(occupancy_stamps, occupancy_stamps[1:]):
            duration = stamp2[0] - stamp1[0]
            if stamp1[1] == -1:
                idle_bar += duration
            else:
                time_bar[stamp1[1]] += duration

        worksheet.write_string('G1', 'occupancy')
        worksheet.write_string('G2', 'idle')
        worksheet.write_string('H1', 'time')
        worksheet.write_number('H2', idle_bar/60)
        for row in range(capacity_dimension + 1):
            worksheet.write_number('G{}'.format(row+3), row)
            worksheet.write_number('H{}'.format(row+3), time_bar[row]/60)

        chart_time_bar.add_series({'name':       'vehicle{}'.format(i),
                                   'categories': '=vehicle{}!$G$2:$G${}'.format(i, capacity_dimension+3),
                                   'values':     '=vehicle{}!$H$2:$H${}'.format(i, capacity_dimension+3)})

        # ************** bar_meters chart ****************
        worksheet.write_string('D1', 'occupancy')
        worksheet.write_string('E1', 'kilometers')
        meters_by_occupancy = res.get('meters_by_occupancy')[i]
        for row, heights in enumerate(meters_by_occupancy, start=2):
            worksheet.write_number('D{}'.format(row), row-2)
            worksheet.write_number('E{}'.format(row), heights/1000)

        chart_bar.add_series({'name':       'vehicle{}'.format(i),
                              'categories': '=vehicle{}!$D$2:$D${}'.format(i, capacity_dimension+2),
                              'values':     '=vehicle{}!$E$2:$E${}'.format(i, capacity_dimension+2)})

    # ************** average series ****************
    worksheet = workbook.add_worksheet('average')
    import itertools
    for row, col in itertools.product(range(1, capacity_dimension + 4), ['E', 'H']):
        worksheet.write_formula('{}{}'.format(col, row),
                                '=AVERAGE(vehicle0:vehicle{}!{}{})'.format(len(res.get('occupancy'))-1, col, row))
    for row, col in itertools.product(range(1, capacity_dimension + 4), ['D', 'G']):
        worksheet.write_formula('{}{}'.format(col, row),
                                '=vehicle0!{}{}'.format(col, row))

    chart_bar.add_series({'name':       'average',
                          'categories': '=average!$D$2:$D$10',
                          'values':     '=average!$E$2:$E$10'})
    chart_time_bar.add_series({'name':       'average',
                               'categories': '=average!$G$2:$G$11',
                               'values':     '=average!$H$2:$H$11'})

    # **************** axis format **********************
    chart.set_x_axis({'name': 'Time of day'})
    chart.set_y_axis({'name': 'Persons in a vehicle'})

    chart_bar.set_x_axis({'name': 'People in a vehicle'})
    chart_bar.set_y_axis({'name': 'Kilometers'})

    chart_time_bar.set_x_axis({'name': 'People in a vehicle'})
    chart_time_bar.set_y_axis({'name': 'minutes'})

    worksheet = writer.sheets['vehicle{}'.format(0)]
    worksheet.insert_chart('K2', chart)
    worksheet.insert_chart('K22', chart_bar)
    worksheet.insert_chart('K42', chart_time_bar)
    writer.save()
