# Sorunlu Kod - Statik analiz sorunlari var

def process_data(data):  # docstring yok D001
    result = []
    for i in range(len(data)):
        for j in range(len(data[i])):
            for k in range(len(data[i][j])):  # 3 seviye ic ice C001
                result.append(data[i][j][k])
    return result

def run_user_input(code):  # docstring yok D001
    return eval(code)  # eval kullanimi S001 guvenlik uyarisi

if __name__ == "__main__":
    print("eval test:", run_user_input("2+2"))
    data = [[[1,2],[3,4]],[[5,6],[7,8]]]
    print("flat:", process_data(data))
